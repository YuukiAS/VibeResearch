"""Project initialization and shared state operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .dashboard import sync_dashboard
from .io import append_jsonl, ensure_dir, next_numeric_id, read_json, read_jsonl, slugify, utc_now, write_json, write_text, write_yaml
from .models import IdeaRecord, ProjectConfig, RunManifest, default_budget, default_state
from .paths import VibePaths
from .timeline import record_event


DIRS = [
    "inbox",
    "state",
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
    "prompts",
]


def init_project(target: str | Path = ".", *, project_name: str | None = None, force: bool = False) -> VibePaths:
    paths = VibePaths(target)
    ensure_dir(paths.root)
    if paths.vibe.exists() and not force:
        paths.require_initialized()
    for rel in DIRS:
        ensure_dir(paths.vibe / rel)

    config = ProjectConfig(project_name=project_name or paths.root.name)
    write_yaml(paths.vibe / "config.yaml", config.model_dump())
    write_json(paths.vibe / "config.json", config.model_dump())

    state = default_state()
    state["updated_at"] = utc_now()
    state["next_action"] = "vibe plan-cycle"
    write_json(paths.state / "state.json", state)
    write_json(paths.state / "lock.json", {"locked": False, "updated_at": utc_now()})
    write_text(paths.state / "memory.md", "# Vibe Memory\n\n")
    touch_jsonl(paths.state / "decisions.jsonl")
    touch_jsonl(paths.state / "open_questions.jsonl")

    write_text(paths.inbox / "ideas.md", "## New Ideas Inbox\n\n- [ ] idea:\n")
    write_text(paths.inbox / "user_prompts.md", "# User Prompts\n\n")
    write_text(paths.inbox / "questions.md", "# Questions\n\n")
    touch_jsonl(paths.inbox / "triage.jsonl")

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
    write_text(paths.research / "wiki" / "index.md", "# Research Wiki\n\n")
    write_text(paths.research / "wiki" / "log.md", "# Research Wiki Log\n\n")
    write_text(paths.research / "deep_requests" / "registry.jsonl", "")

    write_default_templates(paths)
    write_default_prompts(paths)
    write_run_md(paths)
    record_event(paths, "initialized", "Initialized VibeResearch control layer", status="ok")
    sync_dashboard(paths)
    return paths


def touch_jsonl(path: Path) -> None:
    ensure_dir(path.parent)
    if not path.exists():
        path.write_text("")


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
    write_text(paths.root / "RUN.md", text)


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
    existing = [row["idea_id"] for row in read_jsonl(paths.inbox / "triage.jsonl")]
    idea_id = next_numeric_id(existing, "idea")
    record = IdeaRecord(idea_id=idea_id, created_at=utc_now(), source=source, raw_text=text)
    append_jsonl(paths.inbox / "triage.jsonl", record.model_dump())
    with (paths.inbox / "ideas.md").open("a") as handle:
        handle.write(f"- [ ] {idea_id}: {text}\n")
    record_event(paths, "idea_received", text[:180], status="new", payload={"idea_id": idea_id})
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
    existing = list(state.get("cycles", {}).keys())
    cycle_id = next_numeric_id(existing, "c")
    cycle_dir = paths.cycles / cycle_id
    ensure_dir(cycle_dir)
    selected_mode = mode or state.get("portfolio_mode", "exploration")
    write_text(cycle_dir / "portfolio_plan.md", portfolio_plan_template(paths, cycle_id, selected_mode))
    write_text(cycle_dir / "portfolio_review.md", "# Portfolio Review\n\nVerdict: PENDING\n")
    write_yaml(cycle_dir / "resource_plan.yaml", {"cycle_id": cycle_id, "mode": selected_mode, "runs": {}, "cancel_rules": []})
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
"""


def generate_runs(paths: VibePaths, cycle_id: str | None = None, count: int = 3) -> list[str]:
    paths.require_initialized()
    state = read_json(paths.state / "state.json", default_state())
    cycle = cycle_id or state.get("current_cycle_id")
    if not cycle:
        cycle = create_cycle(paths)
        state = read_json(paths.state / "state.json", default_state())
    state.setdefault("runs", {})
    existing = list(state["runs"].keys())
    specs = [
        ("baseline-check", "d001_baseline", "Verify a trusted local baseline and evaluator provenance.", "low"),
        ("diagnostic-check", "d002_diagnostics", "Run cheap diagnostics for evaluator, data, and logging reliability.", "low"),
        ("first-hypothesis", "d003_experiment", "Test the highest-priority research hypothesis from inbox or brief.", "medium"),
        ("literature-scout", "d004_literature", "Collect targeted evidence for the next portfolio decision.", "low"),
        ("external-smoke", "d005_external_repo", "Smoke test a relevant external repo or weight source.", "low"),
        ("seed-repeat", "d006_validation", "Repeat a candidate result for stability.", "medium"),
    ][:count]
    run_ids: list[str] = []
    for short, direction_id, hypothesis, _cost in specs:
        run_id = f"{next_numeric_id(existing + run_ids, 'r')}_{short.replace('-', '_')}"
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
        run_ids.append(run_id)
        record_event(paths, "run_generated", hypothesis, cycle_id=cycle, run_id=run_id, direction_id=direction_id, status="generated")
    (paths.cycles / cycle / "runs.txt").write_text("\n".join(run_ids) + "\n")
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

