"""Dashboard and root progress file rendering."""

from __future__ import annotations

from typing import Any

from .io import read_json, read_jsonl, write_json, write_text
from .paths import VibePaths
from .timeline import sync_timeline_files


def render_status(paths: VibePaths) -> str:
    state = read_json(paths.state / "state.json", {})
    queue = read_json(paths.scheduler / "queue.json", {"queued": []})
    active = read_json(paths.scheduler / "active_jobs.json", {"active": []})
    completed = read_jsonl(paths.scheduler / "completed_jobs.jsonl")
    cycle_id = state.get("current_cycle_id") or "none"
    lines = [
        "# Vibe Status",
        "",
        f"Current cycle: `{cycle_id}`",
        f"Portfolio mode: `{state.get('portfolio_mode', 'exploration')}`",
        f"Status: `{state.get('status', 'unknown')}`",
        f"Next action: `{state.get('next_action', 'vibe next')}`",
    ]
    if state.get("blocked_reason"):
        lines.append(f"Blocked: {state['blocked_reason']}")
    lines.extend(["", "## Runs", ""])
    runs = state.get("runs", {})
    if not runs:
        lines.append("No runs generated yet.")
    else:
        lines.extend(["| Run | Direction | Status | Branch |", "|---|---|---|---|"])
        for run_id, run in sorted(runs.items()):
            lines.append(
                f"| `{run_id}` | `{run.get('direction_id', '')}` | `{run.get('status', '')}` | `{run.get('branch', '')}` |"
            )
    lines.extend(["", "## Scheduler", ""])
    lines.append(f"Queued: {len(queue.get('queued', []))}")
    lines.append(f"Active: {len(active.get('active', []))}")
    lines.append(f"Completed jobs: {len(completed)}")
    return "\n".join(lines) + "\n"


def render_todo(paths: VibePaths) -> str:
    state = read_json(paths.state / "state.json", {})
    ideas = read_jsonl(paths.inbox / "triage.jsonl")
    lines = ["# Vibe TODO", "", "## NOW", ""]
    lines.append(f"- [ ] Run `{state.get('next_action', 'vibe next')}`")
    lines.extend(["", "## NEXT", ""])
    for idea in ideas[-10:]:
        if idea.get("status") in {"new", "triaged"}:
            lines.append(f"- [ ] `{idea['idea_id']}` {idea.get('raw_text', '')[:120]}")
    if len(lines) <= 7:
        lines.append("- [ ] Add an idea or plan the first cycle")
    lines.extend(["", "## BLOCKED", ""])
    if state.get("blocked_reason"):
        lines.append(f"- [ ] {state['blocked_reason']}")
    else:
        lines.append("None.")
    lines.extend(["", "## DONE", ""])
    for event in read_jsonl(paths.dashboard / "timeline.jsonl")[-20:]:
        if event.get("event") in {"run_finished", "merged", "abandoned", "leaderboard_updated"}:
            lines.append(f"- [x] `{event['event']}` {event.get('summary', '')}")
    return "\n".join(lines) + "\n"


def render_leaderboard(paths: VibePaths) -> str:
    history = read_jsonl(paths.leaderboard / "history.jsonl")
    best = read_json(paths.leaderboard / "best.json", {})
    lines = ["# Vibe Leaderboard", ""]
    if best:
        lines.append(f"Best trusted: `{best.get('run_id', 'none')}` metric={best.get('primary_metric', 'n/a')}")
    else:
        lines.append("No trusted best yet.")
    lines.extend(["", "| Cycle | Run | Direction | Metric | Trusted | Status |", "|---|---|---|---:|---|---|"])
    for row in history[-100:]:
        lines.append(
            f"| `{row.get('cycle_id', '')}` | `{row.get('run_id', '')}` | `{row.get('direction_id', '')}` | "
            f"{row.get('primary_metric', '')} | {row.get('trusted', False)} | `{row.get('status', '')}` |"
        )
    return "\n".join(lines) + "\n"


def render_run_table(paths: VibePaths) -> list[dict[str, Any]]:
    state = read_json(paths.state / "state.json", {})
    return [
        {
            "run_id": run_id,
            "direction": run.get("direction_id", ""),
            "status": run.get("status", ""),
            "branch": run.get("branch", ""),
        }
        for run_id, run in sorted(state.get("runs", {}).items())
    ]


def sync_dashboard(paths: VibePaths) -> None:
    status = render_status(paths)
    todo = render_todo(paths)
    leaderboard = render_leaderboard(paths)
    write_text(paths.dashboard / "status.md", status)
    write_text(paths.root / "VIBE_STATUS.md", status)
    write_text(paths.dashboard / "TODO.md", todo)
    write_text(paths.root / "VIBE_TODO.md", todo)
    write_text(paths.root / "VIBE_LEADERBOARD.md", leaderboard)
    write_json(paths.dashboard / "status.json", {"runs": render_run_table(paths)})
    sync_timeline_files(paths)

