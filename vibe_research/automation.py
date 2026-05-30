"""High-level automation helpers for safe single-step and cycle progression."""

from __future__ import annotations

from .codex_adapter import run_codex
from .git_ops import create_branch
from .io import read_json, write_json
from .next_action import compute_next_action
from .papers import auto_method_search
from .paths import VibePaths
from .project import create_cycle, generate_runs, sync_resource_plan_from_portfolio
from .research import literature_refresh_idea, reflect, reflect_cycle, revise_cycle, revise_plan
from .scheduler import collect, monitor, queue_run, review_cycle, review_run, run_dryrun, submit_queue


def auto_next(paths: VibePaths, *, offline: bool = False, dry_submit: bool = True) -> str:
    """Execute one safe next action derived from local state."""

    action, blocked = compute_next_action(paths)
    if blocked:
        return f"blocked: {blocked}"
    parts = action.split()
    if len(parts) < 2 or parts[0] != "vibe":
        return f"noop: {action}"
    command = parts[1]
    target_id = parts[2] if len(parts) > 2 else ""
    if command == "plan-cycle":
        cycle = create_cycle(paths)
        run_codex(paths, "portfolio_planner", cycle, offline=offline)
        sync_resource_plan_from_portfolio(paths, cycle)
        return f"planned {cycle}"
    if command == "review-cycle":
        run_codex(paths, "portfolio_reviewer", target_id, offline=offline)
        review_cycle(paths, target_id)
        return f"reviewed {target_id}"
    if command == "generate-runs":
        try:
            runs = generate_runs(paths, cycle_id=target_id)
        except RuntimeError as exc:
            return f"blocked: {exc}"
        return f"generated {','.join(runs)}"
    if command == "review":
        run_codex(paths, "reviewer", target_id, offline=offline)
        review_run(paths, target_id)
        return f"reviewed {target_id}"
    if command == "branch":
        create_branch(paths, target_id)
        return f"branched {target_id}"
    if command == "patch":
        run_codex(paths, "codex_patch", target_id, offline=offline)
        state = read_json(paths.state / "state.json", {})
        state.setdefault("runs", {}).setdefault(target_id, {})["status"] = "patched"
        state["next_action"] = f"vibe dryrun {target_id}"
        write_json(paths.state / "state.json", state)
        return f"patched {target_id}"
    if command == "dryrun":
        run_dryrun(paths, target_id)
        return f"dryran {target_id}"
    if command == "queue":
        queue_run(paths, target_id)
        return f"queued {target_id}"
    if command == "submit-queue":
        submitted = submit_queue(paths, dry=dry_submit)
        return f"submitted {','.join(submitted)}"
    if command == "monitor":
        monitor(paths)
        if not offline:
            auto_method_search(paths, offline=offline)
        return "monitored"
    if command == "lit-refresh-idea":
        literature_refresh_idea(paths, target_id, offline=offline)
        return f"literature-refreshed {target_id}"
    if command == "collect":
        collect(paths, target_id)
        return f"collected {target_id}"
    if command == "reflect":
        run_codex(paths, "reflect", target_id, offline=offline)
        reflect(paths, target_id, keep_existing=True)
        return f"reflected {target_id}"
    if command == "revise-plan":
        run_codex(paths, "revised_plan", target_id, offline=offline)
        revise_plan(paths, target_id, keep_existing=True, offline=offline)
        return f"revised {target_id}"
    if command == "reflect-cycle":
        run_codex(paths, "cycle_reflect", target_id, offline=offline)
        reflect_cycle(paths, target_id, keep_existing=True)
        return f"reflected {target_id}"
    if command == "revise-cycle":
        run_codex(paths, "cycle_revised_plan", target_id, offline=offline)
        revise_cycle(paths, target_id, keep_existing=True, offline=offline)
        return f"revised {target_id}"
    return f"manual: {action}"


def auto_cycle(paths: VibePaths, *, offline: bool = False, dry_submit: bool = True, max_steps: int = 30) -> list[str]:
    results: list[str] = []
    for _ in range(max_steps):
        result = auto_next(paths, offline=offline, dry_submit=dry_submit)
        results.append(result)
        if result.startswith(("blocked:", "manual:", "submitted", "monitored")):
            break
    return results


def scheduler_explain(paths: VibePaths) -> str:
    queue = read_json(paths.scheduler / "queue.json", {"queued": []}).get("queued", [])
    active = read_json(paths.scheduler / "active_jobs.json", {"active": []}).get("active", [])
    lines = ["# Scheduler Explain", "", f"Queued: {len(queue)}", f"Active: {len(active)}"]
    for item in queue:
        lines.append(f"- queued {item.get('run_id')}: status={item.get('status')} priority={item.get('priority')}")
    for item in active:
        lines.append(f"- active {item.get('run_id')}: backend={item.get('backend')} job={item.get('job_id')}")
    return "\n".join(lines) + "\n"
