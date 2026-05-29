"""Meeting story-pack export."""

from __future__ import annotations

from datetime import datetime
import csv

from .ideas import read_ideas
from .io import ensure_dir, read_json, read_jsonl, write_text
from .papers import list_papers
from .paths import VibePaths
from .timeline import render_timeline_markdown


def export_meeting_report(paths: VibePaths, *, date: str | None = None) -> str:
    paths.require_initialized()
    stamp = date or datetime.now().strftime("%Y%m%d")
    out = ensure_dir(paths.reports / "meeting" / stamp)
    ensure_dir(out / "figures")
    state = read_json(paths.state / "state.json", {})
    ideas = read_ideas(paths)
    deep = read_jsonl(paths.research / "deep_requests" / "registry.jsonl")
    papers = list_papers(paths)
    leaderboard = read_jsonl(paths.leaderboard / "history.jsonl")
    write_text(out / "story.md", render_story(paths, state, ideas, leaderboard, deep))
    write_text(out / "timeline.md", render_timeline_markdown(paths))
    write_text(out / "leaderboard.md", (paths.root / "VIBE_LEADERBOARD.md").read_text() if (paths.root / "VIBE_LEADERBOARD.md").exists() else "")
    write_text(out / "key_runs.md", render_key_runs(paths, state))
    write_text(out / "idea_pool.md", render_idea_pool(ideas))
    write_text(out / "deep_research_status.md", render_deep_status(deep))
    write_text(out / "paper_summary.md", render_paper_summary(papers))
    write_text(out / "slides_outline.md", render_slides_outline(state, ideas, deep))
    write_evidence_csv(out / "evidence_table.csv", leaderboard, deep, papers)
    return str(out)


def render_story(paths: VibePaths, state: dict, ideas: list[dict], leaderboard: list[dict], deep: list[dict]) -> str:
    best = read_json(paths.leaderboard / "best.json", {})
    return f"""# Meeting Story

## Current state
- Status: `{state.get('status', 'unknown')}`
- Current cycle: `{state.get('current_cycle_id') or 'none'}`
- Next action: `{state.get('next_action', 'vibe next')}`

## Main result
Best trusted run: `{best.get('run_id', 'none')}` metric={best.get('primary_metric', 'n/a')}.

## Research direction
Ideas tracked: {len(ideas)}. Deep research requests: {len(deep)}. Leaderboard rows: {len(leaderboard)}.

## Discussion prompts
- Which active idea should move into the next portfolio?
- Which deep research candidate is worth spending external review time on?
- Are scheduler constraints blocking the next experiment?
"""


def render_key_runs(paths: VibePaths, state: dict) -> str:
    lines = ["# Key Runs", ""]
    runs = state.get("runs", {})
    if not runs:
        lines.append("No runs yet.")
    for run_id, run in sorted(runs.items()):
        metrics = read_json(paths.runs / run_id / "metrics.json", {})
        lines.append(f"## {run_id}\n")
        lines.append(f"- Direction: `{run.get('direction_id', '')}`")
        lines.append(f"- Status: `{run.get('status', '')}`")
        lines.append(f"- Metric: `{metrics.get('primary_metric', 'n/a')}`")
        lines.append(f"- Hypothesis: {run.get('hypothesis', '')}\n")
    return "\n".join(lines)


def render_idea_pool(ideas: list[dict]) -> str:
    lines = ["# Idea Pool", "", "| Idea | Status | Priority | Next action | Text |", "|---|---|---|---|---|"]
    for row in ideas:
        lines.append(f"| `{row.get('idea_id','')}` | `{row.get('status','')}` | `{row.get('priority','')}` | {row.get('next_action','')} | {row.get('raw_text','')[:160]} |")
    if len(lines) == 3:
        lines.append("| none | | | | |")
    return "\n".join(lines) + "\n"


def render_deep_status(rows: list[dict]) -> str:
    lines = ["# Deep Research Status", "", "| Request | Status | Kind | Reason | Result |", "|---|---|---|---|---|"]
    for row in rows:
        lines.append(f"| `{row.get('request_id','')}` | `{row.get('status','')}` | `{row.get('kind','science')}` | {row.get('reason','')} | `{row.get('result_path','')}` |")
    if len(lines) == 3:
        lines.append("| none | | | | |")
    return "\n".join(lines) + "\n"


def render_paper_summary(rows: list[dict]) -> str:
    lines = ["# Paper Summary", ""]
    if not rows:
        lines.append("No paper records yet.")
    for row in rows:
        lines.append(f"- `{row.get('paper_id','')}` {row.get('title','')} ({row.get('year','')}) status=`{row.get('status','')}`")
    return "\n".join(lines) + "\n"


def render_slides_outline(state: dict, ideas: list[dict], deep: list[dict]) -> str:
    return f"""# Slides Outline

1. Goal and current cycle
2. Leaderboard and trusted evidence
3. Key run outcomes and guardrails
4. Idea pool decisions ({len(ideas)} tracked)
5. Deep research status ({len(deep)} requests)
6. Next portfolio proposal
7. Open questions for the group
"""


def write_evidence_csv(path, leaderboard: list[dict], deep: list[dict], papers: list[dict]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["kind", "id", "status", "metric_or_title", "path_or_url"])
        for row in leaderboard:
            writer.writerow(["run", row.get("run_id", ""), row.get("status", ""), row.get("primary_metric", ""), ""])
        for row in deep:
            writer.writerow(["deep_research", row.get("request_id", ""), row.get("status", ""), row.get("reason", ""), row.get("request_path", "")])
        for row in papers:
            writer.writerow(["paper", row.get("paper_id", ""), row.get("status", ""), row.get("title", ""), row.get("source_url", "")])
