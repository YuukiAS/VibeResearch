"""Dashboard and root progress file rendering."""

from __future__ import annotations

from typing import Any

from .adapter_onboarding import adapter_readiness
from .ideas import ensure_idea_pool, read_ideas, render_idea_views
from .io import read_json, read_jsonl, write_json, write_text
from .paths import VibePaths
from .portal import build_portal, write_portal_text
from .research_manager import budget_status, load_hypotheses, research_readiness
from .real_experiments import summarize_real_experiment_progress
from .timeline import sync_timeline_files


def render_status(paths: VibePaths) -> str:
    state = read_json(paths.state / "state.json", {})
    queue = read_json(paths.scheduler / "queue.json", {"queued": []})
    active = read_json(paths.scheduler / "active_jobs.json", {"active": []})
    completed = read_jsonl(paths.scheduler / "completed_jobs.jsonl")
    cycle_id = state.get("current_cycle_id") or "none"
    next_action = "vibe monitor" if active.get("active") else state.get("next_action", "vibe next")
    lines = [
        "# Vibe Status",
        "",
        f"Current cycle: `{cycle_id}`",
        f"Portfolio mode: `{state.get('portfolio_mode', 'exploration')}`",
        f"Status: `{state.get('status', 'unknown')}`",
        f"Next action: `{next_action}`",
    ]
    if state.get("blocked_reason"):
        lines.append(f"Blocked: {state['blocked_reason']}")
    readiness = adapter_readiness(paths)
    lines.extend(
        [
            "",
            "## Adapter Readiness",
            "",
            f"Maturity: `{readiness.get('maturity_level', 'missing')}`",
            f"Adapter revision: `{readiness.get('adapter_revision', '')}`",
            f"Ready for instrumentation: `{readiness.get('ready_for_instrumentation', False)}`",
            f"Ready for real experiments: `{readiness.get('ready_for_real_experiments', False)}`",
            f"Ready for Slurm-backed real experiments: `{readiness.get('ready_for_slurm_real_experiments', False)}`",
            "",
            "| Active | Draft/Candidate | Blocked | Missing Answers |",
            "|---|---|---|---|",
            f"| {', '.join(readiness.get('active_capabilities', [])) or 'none'} | "
            f"{', '.join(readiness.get('draft_capabilities', [])) or 'none'} | "
            f"{', '.join(readiness.get('blocked_capabilities', [])) or 'none'} | "
            f"{len(readiness.get('missing_user_answers', []))} |",
        ]
    )
    research = research_readiness(paths)
    real_progress = summarize_real_experiment_progress(paths, write=True)
    budget = budget_status(paths)
    hypotheses = load_hypotheses(paths)
    lines.extend(
        [
            "",
            "## Research Manager",
            "",
            f"Ready for bounded autonomy: `{research.get('ready_for_bounded_autonomy', False)}`",
            f"Active hypotheses: `{len([row for row in hypotheses.values() if row.get('status') in {'active', 'needs_analysis'}])}`",
            f"Budget remaining today: `{budget.get('remaining_daily_gpu_hours', 0)}` GPU-hours, `{budget.get('remaining_daily_jobs', 0)}` jobs",
            f"Real experiment progress: `{real_progress.get('observed_count', 0)}` / `{real_progress.get('target_count', 3)}`",
        ]
    )
    lines.extend(["", "## Runs", ""])
    runs = state.get("runs", {})
    if not runs:
        lines.append("No runs generated yet.")
    else:
        lines.extend(["| Run | Direction | Status | Branch | Cost | Trust | Schema | Adapter Capability |", "|---|---|---|---|---|---|---|---|"])
        for run_id, run in sorted(runs.items()):
            metrics = read_json(paths.runs / run_id / "metrics.json", {})
            adapter_meta = run.get("adapter_metadata", {}) if isinstance(run.get("adapter_metadata", {}), dict) else {}
            lines.append(
                f"| `{run_id}` | `{run.get('direction_id', '')}` | `{run.get('status', '')}` | `{run.get('branch', '')}` | `{run.get('cost', '')}` | "
                f"`{metrics.get('trust_status', '')}` | `{metrics.get('schema_status', '')}` | `{adapter_meta.get('capability_id', '')}` |"
            )
    decisions = read_jsonl(paths.state / "decisions.jsonl")
    if decisions:
        lines.extend(["", "## Recent Decisions", "", "| Target | Decision | Confidence | Rationale |", "|---|---|---|---|"])
        for row in decisions[-10:]:
            lines.append(f"| `{row.get('target_id', '')}` | `{row.get('decision_type', '')}` | `{row.get('confidence', '')}` | {str(row.get('rationale', ''))[:120]} |")
    lines.extend(["", "## Scheduler", ""])
    lines.append(f"Queued: {len(queue.get('queued', []))}")
    lines.append(f"Active: {len(active.get('active', []))}")
    lines.append(f"Completed jobs: {len(completed)}")
    if queue.get("queued"):
        lines.extend(["", "| Queued Run | Status | Priority | Reason |", "|---|---|---:|---|"])
        for item in queue["queued"]:
            lines.append(f"| `{item.get('run_id', '')}` | `{item.get('status', '')}` | {item.get('priority', '')} | {item.get('reason', '')} |")
    if active.get("active"):
        lines.extend(["", "| Active Run | Backend | Job | Status | Log |", "|---|---|---|---|---|"])
        for item in active["active"]:
            lines.append(f"| `{item.get('run_id', '')}` | `{item.get('backend', '')}` | `{item.get('job_id', '')}` | `{item.get('status', '')}` | `{item.get('log_path', '')}` |")
    return "\n".join(lines) + "\n"


def render_todo(paths: VibePaths) -> str:
    state = read_json(paths.state / "state.json", {})
    ideas = read_jsonl(paths.inbox / "triage.jsonl")
    pool = read_ideas(paths) if paths.ideas.exists() else []
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
    readiness = adapter_readiness(paths)
    if not readiness.get("ready_for_real_experiments"):
        for blocker in readiness.get("next_blockers", [])[:8]:
            lines.append(f"- [ ] adapter: {blocker}")
    research = research_readiness(paths)
    if not research.get("ready_for_bounded_autonomy"):
        for question in research.get("open_questions", [])[:8]:
            lines.append(f"- [ ] research: {question.get('question', question.get('question_id', 'open question'))}")
        for missing in research.get("missing_files", [])[:8]:
            lines.append(f"- [ ] research policy missing: {missing}")
    else:
        if not state.get("blocked_reason"):
            lines.append("None.")
    lines.extend(["", "## Idea Intake", ""])
    lines.append('Submit a raw prompt with `vibe idea "..."`.')
    lines.extend(["", "### Recent raw inbox prompts", ""])
    if ideas:
        for idea in ideas[-8:]:
            linked = idea.get("linked_pool_idea_id", idea.get("idea_id", ""))
            lines.append(f"- `{linked}` from `{idea.get('source', '')}`: {idea.get('raw_text', '')[:160]}")
    else:
        lines.append("- none")
    lines.extend(["", "### Recently triaged idea pool entries", ""])
    recent_pool = pool[-8:]
    if recent_pool:
        for idea in recent_pool:
            lines.append(f"- `{idea.get('idea_id', '')}` `{idea.get('status', '')}` next: {idea.get('next_action', '')} - {idea.get('raw_text', '')[:140]}")
    else:
        lines.append("- none")
    lines.extend(["", "### Deep Research Decisions", ""])
    candidates = [idea for idea in pool if idea.get("status") == "needs_deep_research"]
    if candidates:
        for idea in candidates:
            lines.append(f"- [ ] `{idea.get('idea_id', '')}` run `vibe deep-request-from-idea {idea.get('idea_id', '')}`")
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
    best_by_direction = read_json(paths.leaderboard / "best_by_direction.json", {})
    lines = ["# Vibe Leaderboard", ""]
    if best:
        lines.append(f"Best trusted: `{best.get('run_id', 'none')}` metric={best.get('primary_metric', 'n/a')}")
    else:
        lines.append("No trusted best yet.")
    lines.extend(["", "| Cycle | Run | Direction | Branch | Metric | Guardrails | Trusted | Trust Status | Schema | Status |", "|---|---|---|---|---:|---|---|---|---|---|"])
    for row in history[-100:]:
        guardrails = row.get("metrics", {}).get("guardrails", "") if isinstance(row.get("metrics"), dict) else ""
        lines.append(
            f"| `{row.get('cycle_id', '')}` | `{row.get('run_id', '')}` | `{row.get('direction_id', '')}` | `{row.get('branch', '')}` | "
            f"{row.get('primary_metric', '')} | {guardrails} | {row.get('trusted', False)} | `{row.get('trust_status', '')}` | "
            f"`{row.get('schema_status', '')}` | `{row.get('status', '')}` |"
        )
    if best_by_direction:
        lines.extend(["", "## Best By Direction", "", "| Direction | Run | Metric |", "|---|---|---:|"])
        for direction, row in sorted(best_by_direction.items()):
            lines.append(f"| `{direction}` | `{row.get('run_id', '')}` | {row.get('primary_metric', '')} |")
    return "\n".join(lines) + "\n"


def render_run_table(paths: VibePaths) -> list[dict[str, Any]]:
    state = read_json(paths.state / "state.json", {})
    return [
        {
            "run_id": run_id,
            "direction": run.get("direction_id", ""),
            "status": run.get("status", ""),
            "branch": run.get("branch", ""),
            "trust_status": read_json(paths.runs / run_id / "metrics.json", {}).get("trust_status", ""),
            "schema_status": read_json(paths.runs / run_id / "metrics.json", {}).get("schema_status", ""),
            "adapter_metadata": run.get("adapter_metadata", {}),
        }
        for run_id, run in sorted(state.get("runs", {}).items())
    ]


def sync_dashboard(paths: VibePaths) -> None:
    ensure_idea_pool(paths)
    render_idea_views(paths)
    status = render_status(paths)
    todo = render_todo(paths)
    leaderboard = render_leaderboard(paths)
    write_text(paths.dashboard / "status.md", status)
    write_portal_text(paths, "VIBE_STATUS.md", status)
    write_text(paths.dashboard / "TODO.md", todo)
    write_portal_text(paths, "VIBE_TODO.md", todo)
    write_portal_text(paths, "VIBE_LEADERBOARD.md", leaderboard)
    write_json(
        paths.dashboard / "status.json",
        {
            "runs": render_run_table(paths),
            "adapter_readiness": adapter_readiness(paths),
            "research_readiness": research_readiness(paths),
            "research_budget": budget_status(paths),
        },
    )
    sync_timeline_files(paths)
    build_portal(paths)
