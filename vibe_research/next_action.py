"""Operator next-action decision logic."""

from __future__ import annotations

from .io import read_json, read_jsonl
from .paths import VibePaths


def compute_next_action(paths: VibePaths) -> tuple[str, str]:
    state = read_json(paths.state / "state.json", {})
    active = read_json(paths.scheduler / "active_jobs.json", {"active": []}).get("active", [])
    queue = read_json(paths.scheduler / "queue.json", {"queued": []}).get("queued", [])
    if active:
        return "vibe monitor", ""
    if queue:
        return "vibe submit-queue", ""
    for request in read_jsonl(paths.research / "deep_requests" / "registry.jsonl"):
        if request.get("blocking") and request.get("status") != "ingested":
            return "vibe ingest-deep-research " + request.get("request_id", "<request_id>"), "blocked_waiting_deep_research"
    for run_id, run in sorted(state.get("runs", {}).items()):
        run_dir = paths.runs / run_id
        status = run.get("status", "")
        if not has_text(run_dir / "review.md"):
            return f"vibe review {run_id}", ""
        if status in {"generated"}:
            return f"vibe review {run_id}", ""
        if status in {"reviewed"}:
            return f"vibe branch {run_id}", ""
        if status in {"branched", "branch_recorded_no_git"}:
            return f"vibe dryrun {run_id}", ""
        if status == "dryrun_passed":
            return f"vibe queue {run_id}", ""
        if status in {"finished", "submitted_dry"}:
            return f"vibe collect {run_id}", ""
        if status == "collected":
            return f"vibe reflect {run_id}", ""
        if status == "reflected":
            return f"vibe revise-plan {run_id}", ""
        if status == "revised":
            cycle_id = run.get("cycle_id", "")
            cycle_dir = paths.cycles / cycle_id
            if cycle_id and not has_text(cycle_dir / "cycle_reflect.md"):
                return f"vibe reflect-cycle {cycle_id}", ""
    cycle_id = state.get("current_cycle_id", "")
    if cycle_id:
        cycle_dir = paths.cycles / cycle_id
        if not (cycle_dir / "cycle_reflect.md").exists() or not (cycle_dir / "cycle_reflect.md").read_text().strip():
            return f"vibe reflect-cycle {cycle_id}", ""
        if not (cycle_dir / "cycle_revised_plan.md").exists() or not (cycle_dir / "cycle_revised_plan.md").read_text().strip():
            return f"vibe revise-cycle {cycle_id}", ""
    return state.get("next_action") or "vibe plan-cycle", ""


def has_text(path) -> bool:
    return path.exists() and bool(path.read_text().strip())
