"""Project initialization and shared state operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .dashboard import sync_dashboard
from .config import write_config_schema
from .ideas import create_idea as create_pool_idea
from .ideas import ensure_idea_pool
from .ideas import render_idea_views
from .io import append_jsonl, ensure_dir, next_numeric_id, read_json, read_jsonl, read_yaml, slugify, utc_now, write_json, write_text, write_yaml
from .models import IdeaRecord, ProjectConfig, RunManifest, default_budget, default_state
from .papers import connect
from .paths import VibePaths
from .portal import build_portal, install_agents_snippet, write_agents_files, write_portal_text
from .timeline import record_event


DIRS = [
    "inbox",
    "state",
    "project",
    "ideas",
    "cycles",
    "runs",
    "directions",
    "branches",
    "leaderboard/snapshots",
    "scheduler",
    "executor/templates",
    "research/deep_requests",
    "research/raw/papers_pdf",
    "research/raw/papers_md",
    "research/raw/deep_reports",
    "research/raw/repos",
    "research/raw/weights",
    "research/raw/notes",
    "research/raw/assets",
    "research/wiki/papers",
    "research/wiki/concepts",
    "research/wiki/entities",
    "research/wiki/comparisons",
    "research/wiki/gaps",
    "research/wiki/synthesis",
    "dashboard",
    "site",
    "portal",
    "reports/dev",
    "prompts",
]


def init_project(
    target: str | Path = ".",
    *,
    project_name: str | None = None,
    force: bool = False,
    minimal: bool = False,
    root_portal: str = "copy",
    install_agents: bool = False,
    goal: str = "",
    background: str = "",
    brief_file: str | Path | None = None,
    initial_ideas: list[str] | None = None,
    idea_file: str | Path | None = None,
) -> VibePaths:
    paths = VibePaths(target)
    ensure_dir(paths.root)
    if paths.vibe.exists() and not force:
        paths.require_initialized()
    for rel in DIRS:
        ensure_dir(paths.vibe / rel)

    project_brief = load_project_brief(paths, goal=goal, background=background, brief_file=brief_file, minimal=minimal)
    config = ProjectConfig(project_name=project_name or paths.root.name)
    config_data = config.model_dump()
    config_data["project_name"] = project_name or paths.root.name
    config_data["project"] = {
        "name": project_name or paths.root.name,
        "goal": project_brief["goal"],
        "background": project_brief["background"],
        "brief_path": ".vibe/project/brief.md",
        "brief_missing": project_brief["missing"],
    }
    config_data.setdefault("portal", {})["root_mode"] = root_portal
    write_yaml(paths.vibe / "config.yaml", config_data)
    write_json(paths.vibe / "config.json", config_data)
    write_yaml(paths.vibe / "config.local.yaml", {"local": {"notes": "local-only overrides; not auto-merged into config.yaml"}})
    write_text(paths.vibe / ".gitignore", "config.local.yaml\nconfig.detected.yaml\nruntime/env\n")
    write_config_schema(paths)

    state = default_state()
    state["updated_at"] = utc_now()
    state["next_action"] = "vibe plan-cycle"
    state["project_brief_missing"] = project_brief["missing"]
    if project_brief["missing"]:
        state["next_action"] = "add project goal/background with vibe init --goal ... --background ..."
    write_json(paths.state / "state.json", state)
    write_json(paths.state / "lock.json", {"locked": False, "updated_at": utc_now()})
    write_text(paths.state / "memory.md", "# Vibe Memory\n\n")
    touch_jsonl(paths.state / "decisions.jsonl")
    touch_jsonl(paths.state / "open_questions.jsonl")

    write_text(paths.inbox / "ideas.md", "## New Ideas Inbox\n\n- [ ] idea:\n")
    write_text(paths.inbox / "user_prompts.md", "# User Prompts\n\n")
    write_text(paths.inbox / "questions.md", "# Questions\n\n")
    touch_jsonl(paths.inbox / "triage.jsonl")
    ensure_idea_pool(paths)
    render_idea_views(paths)
    write_project_brief(paths, project_brief)
    for text in collect_initial_ideas(initial_ideas or [], idea_file):
        add_idea(paths, text, source="init")

    touch_jsonl(paths.directions / "registry.jsonl")
    write_json(paths.branches / "active.json", {})
    touch_jsonl(paths.branches / "merged.jsonl")
    touch_jsonl(paths.branches / "abandoned.jsonl")

    write_yaml(paths.leaderboard / "goals.yaml", default_goals(paths.root.name))
    write_yaml(paths.leaderboard / "metrics_schema.yaml", default_metric_schema())
    write_json(paths.leaderboard / "best.json", {})
    write_json(paths.leaderboard / "best_by_direction.json", {})
    touch_jsonl(paths.leaderboard / "history.jsonl")

    write_json(paths.scheduler / "queue.json", {"queued": []})
    write_yaml(paths.scheduler / "budget.yaml", default_budget())
    write_json(paths.scheduler / "active_jobs.json", {"active": []})
    touch_jsonl(paths.scheduler / "completed_jobs.jsonl")

    write_text(paths.research / "sources.jsonl", "")
    connect(paths).close()
    write_text(paths.research / "wiki" / "index.md", "# Research Wiki\n\n")
    write_text(paths.research / "wiki" / "log.md", "# Research Wiki Log\n\n")
    write_text(paths.research / "wiki" / "overview.md", "# Research Overview\n\n")
    write_text(paths.research / "deep_requests" / "registry.jsonl", "")

    write_default_templates(paths)
    write_default_prompts(paths)
    write_run_md(paths)
    write_agents_files(paths, config_data["project_name"])
    record_event(paths, "initialized", "Initialized VibeResearch control layer", status="ok")
    sync_dashboard(paths)
    if root_portal != "none":
        build_portal(paths, mode=root_portal, force=force)
    if install_agents:
        install_agents_snippet(paths)
    return paths


def touch_jsonl(path: Path) -> None:
    ensure_dir(path.parent)
    if not path.exists():
        path.write_text("")


def load_project_brief(
    paths: VibePaths,
    *,
    goal: str = "",
    background: str = "",
    brief_file: str | Path | None = None,
    minimal: bool = False,
) -> dict[str, Any]:
    if brief_file:
        source = Path(brief_file).expanduser()
        text = source.read_text()
        parsed_goal = first_nonempty_after(text, ["# Goal", "## Goal", "Goal:"]) or goal
        parsed_background = first_nonempty_after(text, ["# Background", "## Background", "Background:"]) or background or text[:2000]
        return {"goal": parsed_goal, "background": parsed_background, "body": text, "missing": False}
    missing = minimal and not (goal or background)
    if not goal and not background and not minimal:
        goal = f"Define the research objective for {paths.root.name}."
        background = "Project background has not been supplied yet; update .vibe/project/brief.md before serious planning."
    body = f"""# Project Brief

## Goal
{goal or 'MISSING: provide the project research goal.'}

## Background
{background or 'MISSING: provide project background, constraints, datasets, and evaluation context.'}

## Status
{'missing_required_context' if missing else 'ready'}
"""
    return {"goal": goal, "background": background, "body": body, "missing": missing}


def first_nonempty_after(text: str, markers: list[str]) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        for marker in markers:
            if stripped.startswith(marker):
                inline = stripped.removeprefix(marker).strip(" :")
                if inline:
                    return inline
                for candidate in lines[index + 1 :]:
                    if candidate.strip() and not candidate.strip().startswith("#"):
                        return candidate.strip()
    return ""


def write_project_brief(paths: VibePaths, brief: dict[str, Any]) -> None:
    write_text(paths.project / "brief.md", brief["body"])


def collect_initial_ideas(initial_ideas: list[str], idea_file: str | Path | None) -> list[str]:
    ideas = [idea for idea in initial_ideas if idea.strip()]
    if idea_file:
        text = Path(idea_file).expanduser().read_text()
        for line in text.splitlines():
            clean = line.strip("-* \t")
            if clean:
                ideas.append(clean)
    return ideas


def vendor_runtime(paths: VibePaths) -> Path:
    paths.require_initialized()
    runtime = ensure_dir(paths.vibe / "runtime")
    write_text(
        runtime / "README.md",
        """# VibeResearch Runtime

This directory is reserved for repo-local runtime helpers, wrappers, or pinned
launcher scripts when a project needs to vendor operational glue beside its
`.vibe/` state.

The Python package remains installable separately; do not store authoritative
research state outside `.vibe/`.
""",
    )
    write_text(runtime / "env.example", "# Add project-local runtime environment defaults here.\n")
    return runtime


def default_goals(project_name: str) -> dict[str, Any]:
    return {
        "project": project_name,
        "primary_goal": "Improve robust validation performance under fixed protocol",
        "baselines": {"trusted_baseline": {"run_id": "", "description": ""}},
        "metrics": {
            "primary": [{"name": "primary", "direction": "max"}],
            "guardrails": [],
        },
        "comparison_policy": {
            "require_same_split": True,
            "require_same_evaluator": True,
            "require_metric_provenance": True,
            "allow_leaderboard_feedback": False,
        },
    }


def default_metric_schema() -> dict[str, Any]:
    return {
        "primary": {"type": "number", "direction": "max"},
        "guardrails": {},
        "required_provenance": ["git_diff", "env_export", "slurm_record", "metric_schema"],
    }


def write_run_md(paths: VibePaths) -> None:
    text = f"""# Vibe Research Runbook

Target repo: `{paths.root}`

## Recommended Commands

```bash
vibe status
vibe next
vibe idea "try a concrete research idea"
vibe plan-cycle
vibe submit-queue
vibe timeline
vibe leaderboard
```

## New Ideas Inbox

Append new ideas here. The next `vibe plan-cycle` will read and triage them.

- [ ] idea:
"""
    write_portal_text(paths, "RUN.md", text)


def write_default_templates(paths: VibePaths) -> None:
    write_text(
        paths.templates / "slurm_default.sbatch.j2",
        """#!/usr/bin/env bash
#SBATCH --job-name={{ job_name }}
#SBATCH --partition={{ partition }}
#SBATCH --nodes={{ nodes }}
#SBATCH --ntasks={{ ntasks }}
#SBATCH --cpus-per-task={{ cpus_per_task }}
#SBATCH --mem={{ mem }}
#SBATCH --gres={{ gres }}
#SBATCH --time={{ time }}
#SBATCH --output={{ output }}
#SBATCH --error={{ error }}
{{ account_line }}
{{ qos_line }}

set -euo pipefail
cd {{ workdir }}
{{ env_setup }}
{{ command }}
""",
    )
    write_text(paths.templates / "run_status.md.j2", "# Run {{ run_id }}\n\nStatus: {{ status }}\n")
    for name in ["slurm_gpu_short.sbatch.j2", "slurm_gpu_long.sbatch.j2"]:
        write_text(paths.templates / name, (paths.templates / "slurm_default.sbatch.j2").read_text())


def write_default_prompts(paths: VibePaths) -> None:
    prompts = {
        "portfolio_planner.md": "Create a cycle-level portfolio plan. Do not submit jobs.",
        "portfolio_reviewer.md": "Review the entire portfolio and return an explicit verdict.",
        "leader.md": "Coordinate research planning from local state and user directives.",
        "reviewer.md": "Review one run proposal for scientific value and execution safety.",
        "codex_patch.md": "Generate code changes and a manifest; runner owns execution.",
        "reflect.md": "Interpret completed run results only.",
        "revised_plan.md": "Turn reflection into the next concrete decision.",
        "cycle_reflect.md": "Compare all important runs in a cycle.",
        "cycle_revised_plan.md": "Decide the next portfolio mode and resource allocation.",
        "literature.md": "Run targeted literature refresh only when requested.",
        "deep_research_request.md": "Write route-level deep research requests.",
        "deep_research_ingest.md": "Extract decisions from returned deep research reports.",
        "paper_ingest.md": "Convert a paper into wiki, concepts, gaps, and synthesis updates.",
    }
    for name, content in prompts.items():
        write_text(paths.prompts / name, f"# {name}\n\n{content}\n")


def add_idea(paths: VibePaths, text: str, *, source: str = "cli") -> IdeaRecord:
    paths.require_initialized()
    existing = [row.get("raw_id", row.get("idea_id", "")) for row in read_jsonl(paths.inbox / "triage.jsonl")]
    raw_id = next_numeric_id(existing, "raw_")
    pool_record = create_pool_idea(paths, text, source=source, linked_raw_id=raw_id)
    record = IdeaRecord(idea_id=pool_record["idea_id"], created_at=utc_now(), source=source, raw_text=text)
    raw_record = record.model_dump()
    raw_record["raw_id"] = raw_id
    raw_record["linked_pool_idea_id"] = pool_record["idea_id"]
    append_jsonl(paths.inbox / "triage.jsonl", raw_record)
    with (paths.inbox / "ideas.md").open("a") as handle:
        handle.write(f"- [ ] {pool_record['idea_id']} ({raw_id}): {text}\n")
    record_event(paths, "idea_received", text[:180], status="new", payload={"idea_id": pool_record["idea_id"], "raw_id": raw_id})
    sync_dashboard(paths)
    return record


def add_directive(paths: VibePaths, text: str) -> None:
    paths.require_initialized()
    append_jsonl(paths.inbox / "user_prompts.md.jsonl", {"created_at": utc_now(), "directive": text})
    with (paths.vibe / "HUMAN_DIRECTIVE.md").open("a") as handle:
        handle.write(f"\n## {utc_now()}\n\n{text}\n")
    record_event(paths, "directive_received", text[:180], status="new")
    sync_dashboard(paths)


def create_cycle(paths: VibePaths, *, mode: str | None = None) -> str:
    paths.require_initialized()
    state = read_json(paths.state / "state.json", default_state())
    block = cycle_revised_plan_block(paths, state)
    if block:
        raise RuntimeError(block)
    existing = list(state.get("cycles", {}).keys())
    cycle_id = next_numeric_id(existing, "c")
    cycle_dir = paths.cycles / cycle_id
    ensure_dir(cycle_dir)
    selected_mode = mode or state.get("portfolio_mode", "exploration")
    write_text(cycle_dir / "portfolio_plan.md", portfolio_plan_template(paths, cycle_id, selected_mode))
    write_text(cycle_dir / "portfolio_review.md", "# Portfolio Review\n\nVerdict: PENDING\n")
    write_yaml(cycle_dir / "resource_plan.yaml", default_resource_plan(cycle_id, selected_mode))
    write_text(cycle_dir / "runs.txt", "")
    state["current_cycle_id"] = cycle_id
    state["portfolio_mode"] = selected_mode
    state["status"] = "cycle_planned"
    state["next_action"] = f"vibe review-cycle {cycle_id}"
    state["cycles"][cycle_id] = {"status": "planned", "mode": selected_mode, "created_at": utc_now()}
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "cycle_planned", f"Created portfolio plan for {cycle_id}", cycle_id=cycle_id, status="planned")
    sync_dashboard(paths)
    return cycle_id


def cycle_revised_plan_block(paths: VibePaths, state: dict[str, Any]) -> str:
    terminal = {"revised", "merged", "abandoned", "cancelled"}
    for cycle_id, cycle in state.get("cycles", {}).items():
        cycle_runs = [run for run in state.get("runs", {}).values() if run.get("cycle_id") == cycle_id]
        if not cycle_runs:
            continue
        all_terminal = all(run.get("status") in terminal for run in cycle_runs)
        revised_path = paths.cycles / cycle_id / "cycle_revised_plan.md"
        has_revised = revised_path.exists() and bool(revised_path.read_text().strip())
        if all_terminal and cycle.get("status") != "revised" and not has_revised:
            return f"Cycle {cycle_id} requires cycle_revised_plan.md before planning another cycle"
    return ""


def portfolio_plan_template(paths: VibePaths, cycle_id: str, mode: str) -> str:
    ideas = read_jsonl(paths.inbox / "triage.jsonl")[-20:]
    idea_lines = "\n".join(f"- {row['idea_id']}: {row['raw_text']}" for row in ideas) or "- none"
    return f"""# Portfolio Plan for {cycle_id}

## Stage
{mode}

## Current leaderboard summary
No trusted improvement has been recorded yet.

## User ideas and directives considered
{idea_lines}

## Candidate directions
- d001_baseline: establish or verify a trusted baseline.
- d002_diagnostics: cheap evaluator and provenance checks.
- d003_experiment: first research hypothesis from the inbox or project brief.

## Selected runs
- r001_baseline_check: direction=d001_baseline, cost=low, expected learning=baseline validity.
- r002_diagnostic_check: direction=d002_diagnostics, cost=low, expected learning=evaluator reliability.
- r003_first_hypothesis: direction=d003_experiment, cost=medium, expected learning=whether the first research hypothesis is promising.

## Dependency graph
r001 and r002 can run independently. r003 should wait for r001 if baseline validity is unknown.

## Resource budget
Use scheduler budget from `.vibe/scheduler/budget.yaml`; cheap diagnostics first.

## Portfolio success criteria
At least one trusted baseline/diagnostic result and one actionable next direction.

## Stop or shrink criteria
Pause a direction after repeated guardrail failures or missing metric provenance.

## Idea pool update
Selected ideas are considered from `.vibe/ideas/registry.jsonl`; defer, reject, or mark deep research candidates during revised planning.
"""


def default_resource_plan(cycle_id: str, mode: str) -> dict[str, Any]:
    return {
        "cycle_id": cycle_id,
        "mode": mode,
        "max_parallel_jobs": 3,
        "max_gpu_jobs": 2,
        "runs": {
            "baseline-check": {
                "priority": 1,
                "direction_id": "d001_baseline",
                "hypothesis": "Verify a trusted local baseline and evaluator provenance.",
                "cost": "low",
                "can_parallel": True,
                "depends_on": [],
                "cancel_if_failed": [],
            },
            "diagnostic-check": {
                "priority": 1,
                "direction_id": "d002_diagnostics",
                "hypothesis": "Run cheap diagnostics for evaluator, data, and logging reliability.",
                "cost": "low",
                "can_parallel": True,
                "depends_on": [],
                "cancel_if_failed": [],
            },
            "first-hypothesis": {
                "priority": 2,
                "direction_id": "d003_experiment",
                "hypothesis": "Test the highest-priority research hypothesis from inbox or project brief.",
                "cost": "medium",
                "can_parallel": True,
                "depends_on": ["baseline-check"],
                "cancel_if_failed": [],
            },
        },
        "cancel_rules": [
            {"if": "baseline-check fails", "cancel": ["first-hypothesis"]},
            {"if": "three runs in same direction fail guardrails", "pause_direction": True},
        ],
    }


def load_resource_plan(paths: VibePaths, cycle_id: str) -> dict[str, Any]:
    plan = read_yaml(paths.cycles / cycle_id / "resource_plan.yaml", {})
    if not isinstance(plan, dict) or not plan.get("runs"):
        state = read_json(paths.state / "state.json", default_state())
        plan = default_resource_plan(cycle_id, state.get("portfolio_mode", "exploration"))
        write_yaml(paths.cycles / cycle_id / "resource_plan.yaml", plan)
    return plan


def sync_resource_plan_from_portfolio(paths: VibePaths, cycle_id: str) -> dict[str, Any]:
    """Ensure a machine resource plan exists after a human/Codex plan is written."""

    plan = load_resource_plan(paths, cycle_id)
    plan["cycle_id"] = cycle_id
    plan.setdefault("mode", read_json(paths.state / "state.json", {}).get("portfolio_mode", "exploration"))
    plan.setdefault("runs", {})
    plan.setdefault("cancel_rules", [])
    write_yaml(paths.cycles / cycle_id / "resource_plan.yaml", plan)
    return plan


def generate_runs(paths: VibePaths, cycle_id: str | None = None, count: int = 3) -> list[str]:
    paths.require_initialized()
    state = read_json(paths.state / "state.json", default_state())
    cycle = cycle_id or state.get("current_cycle_id")
    if not cycle:
        cycle = create_cycle(paths)
        state = read_json(paths.state / "state.json", default_state())
    cycle_state = state.get("cycles", {}).get(cycle, {})
    if cycle_state.get("review_verdict") in {"BLOCK_PORTFOLIO", "REVISE_PORTFOLIO"} or cycle_state.get("status") == "blocked":
        raise RuntimeError(f"Cycle {cycle} is blocked by portfolio review: {cycle_state.get('review_verdict', '')}")
    state.setdefault("runs", {})
    existing = list(state["runs"].keys())
    resource_plan = load_resource_plan(paths, cycle)
    plan_runs = resource_plan.get("runs", {})
    cancel_map: dict[str, list[str]] = {}
    for rule in resource_plan.get("cancel_rules", []):
        if isinstance(rule, dict):
            text = str(rule.get("if", ""))
            source = text.split()[0] if text else ""
            if source and isinstance(rule.get("cancel"), list):
                cancel_map.setdefault(source, []).extend(str(item) for item in rule["cancel"])
    specs = []
    if isinstance(plan_runs, dict) and plan_runs:
        for short, spec in list(plan_runs.items())[:count]:
            if isinstance(spec, dict):
                specs.append(
                    (
                        slugify(short, 32),
                        spec.get("direction_id", "d000_unknown"),
                        spec.get("hypothesis", spec.get("expected_learning", short)),
                        spec.get("cost", "low"),
                        int(spec.get("priority", 100)),
                        list(spec.get("depends_on", [])),
                        list(spec.get("cancel_if_failed", [])) + cancel_map.get(str(short), []),
                    )
                )
    if not specs:
        specs = [
            ("baseline-check", "d001_baseline", "Verify a trusted local baseline and evaluator provenance.", "low", 1, [], []),
            ("diagnostic-check", "d002_diagnostics", "Run cheap diagnostics for evaluator, data, and logging reliability.", "low", 1, [], []),
            ("first-hypothesis", "d003_experiment", "Test the highest-priority research hypothesis from inbox or brief.", "medium", 2, [], []),
            ("literature-scout", "d004_literature", "Collect targeted evidence for the next portfolio decision.", "low", 3, [], []),
            ("external-smoke", "d005_external_repo", "Smoke test a relevant external repo or weight source.", "low", 3, [], []),
            ("seed-repeat", "d006_validation", "Repeat a candidate result for stability.", "medium", 4, [], []),
        ][:count]
    run_ids: list[str] = []
    name_to_run_id: dict[str, str] = {}
    for short, direction_id, hypothesis, cost, priority, depends_on, cancel_if_failed in specs:
        run_id = f"{next_numeric_id(existing + run_ids, 'r')}_{short.replace('-', '_')}"
        name_to_run_id[short] = run_id
        resolved_deps = [name_to_run_id.get(str(dep), str(dep)) for dep in depends_on]
        resolved_cancel = [name_to_run_id.get(str(dep), str(dep)) for dep in cancel_if_failed]
        branch = f"vibe/{run_id.replace('_', '-')}"
        manifest = RunManifest(
            run_id=run_id,
            cycle_id=cycle,
            direction_id=direction_id,
            branch=branch,
            hypothesis=hypothesis,
            change_summary="Generated scaffold; fill in project-specific command before submit.",
            expected_learning=hypothesis,
            dryrun={"command": "python -c 'print(\"vibe dryrun placeholder\")'", "max_minutes": 5},
            entrypoint={"type": "local", "command": "python -c 'print(\"vibe run placeholder\")'"},
            resources={
                "gpu": 0 if cost == "low" else 1,
                "cpus": 1 if cost == "low" else 4,
                "mem_gb": 4 if cost == "low" else 16,
                "time": "00:30:00" if cost == "low" else "04:00:00",
                "preferred_partitions": ["gpu_short"],
                "fallback_partitions": ["gpu", "a100", "general_gpu"],
            },
            dependencies={"run_after": resolved_deps, "cancel_if_failed": resolved_cancel},
        )
        run_dir = paths.runs / run_id
        ensure_dir(run_dir / "artifacts")
        write_text(run_dir / "proposal.md", proposal_template(manifest))
        write_text(run_dir / "review.md", "# Run Review\n\nVerdict: PENDING\n")
        write_yaml(run_dir / "manifest.yaml", manifest.model_dump())
        write_json(run_dir / "manifest.json", manifest.model_dump())
        write_text(run_dir / "patch.diff", "")
        write_text(run_dir / "branch.txt", branch + "\n")
        write_json(run_dir / "launch.json", {})
        write_text(run_dir / "monitor.jsonl", "")
        write_json(run_dir / "metrics.json", {})
        write_text(run_dir / "result.md", "# Result\n\nPending.\n")
        write_text(run_dir / "reflect.md", "")
        write_text(run_dir / "revised_plan.md", "")
        write_json(run_dir / "literature_refresh.json", {})
        write_text(run_dir / "deep_research_request.md", "")
        write_yaml(run_dir / "next_manifest.yaml", {})
        state["runs"][run_id] = manifest.model_dump()
        state["runs"][run_id]["status"] = "generated"
        state["runs"][run_id]["priority"] = priority
        state["runs"][run_id]["cost"] = cost
        run_ids.append(run_id)
        record_event(paths, "run_generated", hypothesis, cycle_id=cycle, run_id=run_id, direction_id=direction_id, status="generated")
    for run_id in run_ids:
        run = state["runs"][run_id]
        deps = run.get("dependencies", {})
        deps["run_after"] = [name_to_run_id.get(str(item), str(item)) for item in deps.get("run_after", [])]
        deps["cancel_if_failed"] = [name_to_run_id.get(str(item), str(item)) for item in deps.get("cancel_if_failed", [])]
        run["dependencies"] = deps
        write_yaml(paths.runs / run_id / "manifest.yaml", run)
        write_json(paths.runs / run_id / "manifest.json", run)
    (paths.cycles / cycle / "runs.txt").write_text("\n".join(run_ids) + "\n")
    expanded_plan = resource_plan
    expanded_plan["generated_run_ids"] = run_ids
    write_yaml(paths.cycles / cycle / "resource_plan.yaml", expanded_plan)
    state["status"] = "runs_generated"
    state["next_action"] = f"vibe review {run_ids[0]}" if run_ids else "vibe next"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    sync_dashboard(paths)
    return run_ids


def proposal_template(manifest: RunManifest) -> str:
    return f"""# Proposal for {manifest.run_id}

## Hypothesis
{manifest.hypothesis}

## Direction
{manifest.direction_id}

## Expected learning
{manifest.expected_learning}

## Minimum execution
Fill the project-specific command in `manifest.yaml`, then run `vibe dryrun {manifest.run_id}`.
"""
