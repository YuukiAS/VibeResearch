"""Codex CLI collaboration boundary."""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import load_config
from .io import ensure_dir, next_numeric_id, read_jsonl, utc_now, write_json, write_text
from .paths import VibePaths
from .timeline import record_event


READ_ONLY_ROLES = {
    "portfolio_planner",
    "portfolio_reviewer",
    "reviewer",
    "reflect",
    "cycle_reflect",
    "revised_plan",
    "cycle_revised_plan",
    "literature",
    "deep_research_request",
    "deep_research_ingest",
    "paper_ingest",
}


@dataclass
class CodexCallResult:
    call_id: str
    role: str
    target_id: str
    artifact_path: Path
    exit_code: int
    call_dir: Path
    last_message: str
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def prompt_packet(paths: VibePaths, role: str, target_id: str = "") -> str:
    prompt_path = paths.prompts / f"{role}.md"
    prompt = prompt_path.read_text() if prompt_path.exists() else f"# {role}\n"
    context = context_packet(paths, target_id)
    output_path = artifact_path(paths, role, target_id)
    return f"""{prompt}

## Deterministic Boundary
Write artifacts only. Do not submit long-running jobs. The local runner owns
dry-run, queue, submit, monitor, collect, metrics, and provenance.
For non-patch roles, do not edit repository files directly. Return the complete
artifact body as your final answer. It will be written to `{output_path}` by the
deterministic runner.
For patch role, edit code if needed, update the run manifest, and summarize the
changes. Do not start long-running training or Slurm jobs.

## Target
{target_id}

## Local State Context
{context}
"""


def artifact_path(paths: VibePaths, role: str, target_id: str) -> Path:
    mapped = artifact_filename(role, target_id)
    if target_id.startswith("r"):
        if mapped == "patch.diff":
            return paths.runs / target_id / "patch.diff"
        return paths.runs / target_id / mapped
    if target_id.startswith("c"):
        return paths.cycles / target_id / mapped
    if target_id.startswith("dr"):
        return paths.research / "deep_requests" / f"{target_id}.md"
    return paths.vibe / mapped


def artifact_filename(role: str, target_id: str) -> str:
    if role == "portfolio_planner":
        return "portfolio_plan.md"
    if role == "portfolio_reviewer":
        return "portfolio_review.md"
    if role == "reviewer":
        return "review.md"
    if role == "codex_patch":
        return "patch.diff"
    if role == "reflect":
        return "reflect.md"
    if role == "cycle_reflect":
        return "cycle_reflect.md"
    if role == "revised_plan":
        return "revised_plan.md"
    if role == "cycle_revised_plan":
        return "cycle_revised_plan.md"
    if role == "literature":
        return "literature_refresh.md"
    if role == "deep_research_request":
        return "deep_research_request.md"
    if role == "deep_research_ingest":
        return "deep_research_ingest.md"
    if role == "paper_ingest":
        return "paper_ingest.md"
    return f"{role}.md"


def run_codex(
    paths: VibePaths,
    role: str,
    target_id: str = "",
    *,
    offline: bool = False,
    search: bool = False,
    model: str | None = None,
) -> CodexCallResult:
    """Run Codex non-interactively and write the resulting artifact.

    Offline mode is deterministic and used in tests or when Codex is absent. It
    writes a structurally valid fallback artifact but records the call exactly as
    a real Codex call would.
    """

    config = load_config(paths)
    calls_dir = ensure_dir(paths.vibe / "codex_calls")
    existing = [row.get("call_id", "") for row in read_jsonl(calls_dir / "registry.jsonl")]
    call_id = next_numeric_id(existing, "call")
    call_dir = ensure_dir(calls_dir / call_id)
    prompt = prompt_packet(paths, role, target_id)
    output = artifact_path(paths, role, target_id)
    last_message_path = call_dir / "last_message.md"
    stdout_path = call_dir / "stdout.txt"
    stderr_path = call_dir / "stderr.txt"
    write_text(call_dir / "prompt.md", prompt)
    start = time.time()

    if offline:
        last_message = offline_artifact(role, target_id)
        stdout = ""
        stderr = ""
        returncode = 0
        write_text(last_message_path, last_message)
    else:
        command = [
            "codex",
            "exec",
            "-C",
            str(paths.root),
            "--ask-for-approval",
            config.get("codex", {}).get("approval_policy", "never"),
            "--sandbox",
            codex_sandbox_for(role, config),
            "--output-last-message",
            str(last_message_path),
        ]
        selected_model = model or config.get("codex", {}).get("model", "")
        if selected_model:
            command.extend(["--model", selected_model])
        if search or (role == "literature" and config.get("codex", {}).get("enable_search_for_literature", True)):
            command.append("--search")
        command.append("-")
        proc = subprocess.run(command, input=prompt, text=True, capture_output=True, cwd=paths.root, check=False)
        stdout = proc.stdout
        stderr = proc.stderr
        returncode = proc.returncode
        if last_message_path.exists():
            last_message = last_message_path.read_text()
        else:
            last_message = stdout
            write_text(last_message_path, last_message)

    write_text(stdout_path, stdout)
    write_text(stderr_path, stderr)
    if role != "codex_patch":
        write_text(output, last_message)
    else:
        diff = git_diff(paths.root)
        write_text(output, diff or last_message)

    duration = time.time() - start
    record = {
        "call_id": call_id,
        "role": role,
        "target_id": target_id,
        "created_at": utc_now(),
        "duration_seconds": round(duration, 3),
        "exit_code": returncode,
        "artifact_path": str(output),
        "call_dir": str(call_dir),
        "offline": offline,
    }
    write_json(call_dir / "call.json", record)
    with (calls_dir / "registry.jsonl").open("a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    record_event(paths, "codex_artifact_generated", f"{role} -> {output.name}", cycle_id=target_id if target_id.startswith("c") else "", run_id=target_id if target_id.startswith("r") else "", status="ok" if returncode == 0 else "failed", payload=record)
    return CodexCallResult(call_id, role, target_id, output, returncode, call_dir, last_message, stdout, stderr)


def codex_sandbox_for(role: str, config: dict[str, Any]) -> str:
    codex = config.get("codex", {})
    if role == "codex_patch":
        return codex.get("sandbox", {}).get("patch_role", "workspace-write")
    return codex.get("sandbox", {}).get("read_roles", "read-only")


def context_packet(paths: VibePaths, target_id: str) -> str:
    snippets = []
    for rel in [
        "VIBE_STATUS.md",
        "VIBE_LEADERBOARD.md",
        "VIBE_TODO.md",
        ".vibe/inbox/triage.jsonl",
        ".vibe/state/state.json",
    ]:
        path = paths.root / rel
        if path.exists():
            snippets.append(f"### {rel}\n{path.read_text()[-8000:]}")
    if target_id.startswith("r"):
        run_dir = paths.runs / target_id
        for name in ["proposal.md", "review.md", "manifest.json", "metrics.json", "reflect.md", "revised_plan.md"]:
            path = run_dir / name
            if path.exists():
                snippets.append(f"### .vibe/runs/{target_id}/{name}\n{path.read_text()[-8000:]}")
    if target_id.startswith("c"):
        cycle_dir = paths.cycles / target_id
        for name in ["portfolio_plan.md", "portfolio_review.md", "resource_plan.yaml", "cycle_reflect.md", "cycle_revised_plan.md"]:
            path = cycle_dir / name
            if path.exists():
                snippets.append(f"### .vibe/cycles/{target_id}/{name}\n{path.read_text()[-8000:]}")
    return "\n\n".join(snippets) or "No local context files found."


def offline_artifact(role: str, target_id: str) -> str:
    title = role.replace("_", " ").title()
    if role == "portfolio_reviewer":
        return "# Portfolio Review\n\nVerdict: APPROVE_WITH_RESOURCE_GUARDS\n\nGuards: dry-run first; respect scheduler budget.\n"
    if role == "reviewer":
        return f"# Run Review for {target_id}\n\nVerdict: APPROVE_WITH_GUARDS\n\nGuards: dry-run must pass and metric provenance must be collected.\n"
    if role == "portfolio_planner":
        return f"# Portfolio Plan for {target_id or 'next cycle'}\n\n## Stage\nexploration\n\n## Current leaderboard summary\nUse current VIBE_LEADERBOARD.md.\n\n## User ideas and directives considered\nSee inbox.\n\n## Candidate directions\n- baseline\n- diagnostics\n- experiment\n\n## Selected runs\n- baseline check\n- diagnostic check\n- first hypothesis\n\n## Dependency graph\nCheap diagnostics first.\n\n## Resource budget\nUse scheduler budget.\n\n## Portfolio success criteria\nAt least one trusted result or actionable direction decision.\n\n## Stop or shrink criteria\nStop repeated guardrail failures.\n"
    if role == "reflect":
        return f"# Reflect for {target_id}\n\n## Result interpretation\nOffline fallback; inspect metrics.json.\n\n## Hypothesis status\nneeds evidence\n\n## Failure or success analysis\nRequire revised plan before next action.\n"
    if role == "cycle_reflect":
        return f"# Cycle Reflect for {target_id}\n\n## Run comparison\nOffline fallback; compare run metrics and revised plans.\n"
    if role == "revised_plan":
        return f"# Revised Plan for {target_id}\n\n## Result interpretation\nOffline fallback.\n\n## Decision\ncollect_more_metrics\n\n## Plan update\nContinue only after review.\n\n## Required changes\nnone\n\n## Evidence needed\nnone\n\n## Literature refresh decision\nno\n\n## Deep research decision\nno\n\n## Portfolio implication\nNo automatic promotion.\n\n## Next experiment proposal\nnone\n\n## Stop condition\nStop after repeated guardrail failure.\n"
    if role == "cycle_revised_plan":
        return f"# Cycle Revised Plan for {target_id}\n\n## Cycle-level interpretation\nOffline fallback.\n\n## Direction decisions\ncontinue current directions.\n\n## Portfolio mode update\nbalanced\n\n## Next portfolio sketch\nRun cheap diagnostics before expensive training.\n\n## Resource update\nUse scheduler budget.\n\n## Literature and deep research decision\nLiterature refresh: no. Deep research: no.\n\n## User decision needed\nnone\n\n## Stop condition\nStop failed directions after repeated guardrail failure.\n"
    if role == "deep_research_request":
        return f"# Deep Research Request: {target_id or 'request'}\n\n## Project context\nOffline fallback.\n\n## Current experimental evidence\nSee local status.\n\n## Existing local knowledge\nSee wiki.\n\n## Core research question\nRoute selection.\n\n## Required comparisons\nCompare methods, repos, weights, datasets, risks.\n\n## What counts as useful output\nActionable experiments with evidence.\n\n## What to avoid\nGeneric unsourced survey.\n\n## Expected deliverable\nEvidence table, method map, risk assessment, next experiments, citations.\n"
    return f"# {title} for {target_id}\n\nGenerated by offline fallback.\n"


def git_diff(root: Path) -> str:
    proc = subprocess.run(["git", "diff", "--", "."], cwd=root, text=True, capture_output=True, check=False)
    return proc.stdout if proc.returncode == 0 else ""
