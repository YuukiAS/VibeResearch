"""Maintained idea pool operations."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .io import append_jsonl, ensure_dir, next_numeric_id, read_jsonl, utc_now, write_text
from .papers import list_papers
from .paths import VibePaths
from .timeline import record_event


IDEA_STATUSES = {
    "new",
    "triaged",
    "active",
    "actionable_next_run",
    "queued_for_cycle",
    "needs_literature_refresh",
    "needs_deep_research",
    "waiting_user_decision",
    "implemented",
    "backlog",
    "rejected",
    "archived",
    "superseded",
}
IDEA_FILES = {
    "pool.md": {"new", "triaged", "active", "actionable_next_run", "queued_for_cycle", "needs_literature_refresh", "needs_deep_research", "waiting_user_decision", "backlog"},
    "active.md": {"active", "actionable_next_run", "queued_for_cycle"},
    "deep_research_candidates.md": {"needs_deep_research"},
    "backlog.md": {"backlog", "new", "triaged", "needs_literature_refresh", "waiting_user_decision"},
    "rejected.md": {"rejected"},
    "archive.md": {"archived", "superseded", "implemented"},
}


@dataclass
class IdeaPoolRecord:
    idea_id: str
    created_at: str
    updated_at: str
    source: str
    raw_text: str
    status: str = "new"
    priority: str = "medium"
    confidence: str = "unknown"
    linked_evidence: list[str] | None = None
    rationale: str = ""
    current_evidence: str = ""
    next_action: str = "triage"
    archive_reason: str = ""
    rejection_reason: str = ""
    linked_raw_id: str = ""
    linked_deep_request_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "idea_id": self.idea_id,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
            "raw_text": self.raw_text,
            "status": self.status,
            "priority": self.priority,
            "confidence": self.confidence,
            "linked_evidence": self.linked_evidence or [],
            "rationale": self.rationale,
            "current_evidence": self.current_evidence,
            "next_action": self.next_action,
            "archive_reason": self.archive_reason,
            "rejection_reason": self.rejection_reason,
            "linked_raw_id": self.linked_raw_id,
            "linked_deep_request_id": self.linked_deep_request_id,
        }


def ensure_idea_pool(paths: VibePaths) -> None:
    ensure_dir(paths.ideas)
    registry = paths.ideas / "registry.jsonl"
    if not registry.exists():
        registry.write_text("")
    for name in IDEA_FILES:
        path = paths.ideas / name
        if not path.exists():
            write_text(path, f"# {title_for_file(name)}\n\nNo ideas yet.\n")


def title_for_file(name: str) -> str:
    return name.removesuffix(".md").replace("_", " ").title()


def read_ideas(paths: VibePaths) -> list[dict[str, Any]]:
    ensure_idea_pool(paths)
    return read_jsonl(paths.ideas / "registry.jsonl")


def write_ideas(paths: VibePaths, ideas: list[dict[str, Any]]) -> None:
    ensure_idea_pool(paths)
    text = "".join(json.dumps(row, sort_keys=True) + "\n" for row in ideas)
    write_text(paths.ideas / "registry.jsonl", text)
    render_idea_views(paths, ideas)


def next_idea_id(paths: VibePaths) -> str:
    return next_numeric_id([row.get("idea_id", "") for row in read_ideas(paths)], "idea_")


def create_idea(
    paths: VibePaths,
    text: str,
    *,
    source: str = "cli",
    linked_raw_id: str = "",
    status: str = "new",
    priority: str = "medium",
    confidence: str = "unknown",
) -> dict[str, Any]:
    ensure_idea_pool(paths)
    now = utc_now()
    record = IdeaPoolRecord(
        idea_id=next_idea_id(paths),
        created_at=now,
        updated_at=now,
        source=source,
        raw_text=text,
        status=status,
        priority=priority,
        confidence=confidence,
        linked_raw_id=linked_raw_id,
    ).to_dict()
    append_jsonl(paths.ideas / "registry.jsonl", record)
    render_idea_views(paths)
    record_event(paths, "idea_pool_created", text[:180], status=status, payload={"idea_id": record["idea_id"]})
    return record


def update_idea(paths: VibePaths, idea_id: str, **updates: Any) -> dict[str, Any]:
    ideas = read_ideas(paths)
    for row in ideas:
        if row.get("idea_id") == idea_id:
            status = updates.get("status", row.get("status", "new"))
            if status not in IDEA_STATUSES:
                raise ValueError(f"Unsupported idea status: {status}")
            row.update({key: value for key, value in updates.items() if value is not None})
            row["updated_at"] = utc_now()
            write_ideas(paths, ideas)
            record_event(paths, "idea_pool_updated", f"{idea_id}: {row.get('status')}", status=row.get("status", ""), payload=row)
            return row
    raise ValueError(f"Unknown idea: {idea_id}")


def get_idea(paths: VibePaths, idea_id: str) -> dict[str, Any]:
    for row in read_ideas(paths):
        if row.get("idea_id") == idea_id:
            return row
    raise ValueError(f"Unknown idea: {idea_id}")


def triage_ideas(paths: VibePaths) -> list[dict[str, Any]]:
    changed: list[dict[str, Any]] = []
    for row in read_ideas(paths):
        if row.get("status") != "new":
            continue
        text = row.get("raw_text", "").lower()
        if any(token in text for token in ["deep research", "survey", "literature", "unknown", "compare"]):
            row = update_idea(
                paths,
                row["idea_id"],
                status="needs_deep_research",
                rationale="Triage detected external evidence or comparison need.",
                next_action=f"vibe deep-request-from-idea {row['idea_id']}",
            )
        else:
            row = update_idea(
                paths,
                row["idea_id"],
                status="triaged",
                rationale="Triage kept idea available for future portfolio planning.",
                next_action="consider in next plan-cycle",
            )
        changed.append(row)
    return changed


def promote_idea(paths: VibePaths, idea_id: str) -> dict[str, Any]:
    return update_idea(paths, idea_id, status="active", next_action="include in next portfolio plan")


def reject_idea(paths: VibePaths, idea_id: str, reason: str = "") -> dict[str, Any]:
    return update_idea(paths, idea_id, status="rejected", rejection_reason=reason or "rejected by operator", next_action="none")


def archive_idea(paths: VibePaths, idea_id: str, reason: str = "") -> dict[str, Any]:
    return update_idea(paths, idea_id, status="archived", archive_reason=reason or "archived by operator", next_action="none")


def clean_ideas(paths: VibePaths) -> dict[str, int]:
    seen: set[str] = set()
    kept: list[dict[str, Any]] = []
    duplicates = 0
    evidence_gaps = 0
    for row in read_ideas(paths):
        key = " ".join(row.get("raw_text", "").lower().split())
        if key and key in seen:
            row["status"] = "superseded"
            row["archive_reason"] = "duplicate idea text"
            duplicates += 1
        if row.get("status") in {"active", "actionable_next_run", "queued_for_cycle"} and not row.get("linked_evidence"):
            row["current_evidence"] = (row.get("current_evidence", "") + " | needs linked evidence").strip(" |")
            evidence_gaps += 1
        if row.get("status") == "implemented":
            row["status"] = "archived"
            row["archive_reason"] = row.get("archive_reason") or "implemented idea archived by clean"
        seen.add(key)
        kept.append(row)
    write_ideas(paths, kept)
    return {"duplicates_marked": duplicates, "evidence_gaps_marked": evidence_gaps, "total": len(kept)}


def build_deep_request_from_idea(paths: VibePaths, idea_id: str) -> str:
    idea = get_idea(paths, idea_id)
    state = (paths.state / "state.json").read_text() if (paths.state / "state.json").exists() else "{}"
    leaderboard = (paths.leaderboard / "best_by_direction.json").read_text() if (paths.leaderboard / "best_by_direction.json").exists() else "{}"
    wiki_index = (paths.research / "wiki" / "index.md").read_text() if (paths.research / "wiki" / "index.md").exists() else ""
    project_brief = (paths.project / "brief.md").read_text() if (paths.project / "brief.md").exists() else ""
    papers = list_papers(paths)[:20]
    open_questions = (paths.state / "open_questions.jsonl").read_text() if (paths.state / "open_questions.jsonl").exists() else ""
    reviewer_notes = collect_existing_text(paths.runs, ["review.md", "reflect.md", "revised_plan.md"], limit=12000)
    cycle_notes = collect_existing_text(paths.cycles, ["portfolio_plan.md", "cycle_reflect.md", "cycle_revised_plan.md"], limit=12000)
    scheduler = (paths.scheduler / "budget.yaml").read_text() if (paths.scheduler / "budget.yaml").exists() else ""
    existing = [row.get("request_id", "") for row in read_jsonl(paths.research / "deep_requests" / "registry.jsonl")]
    request_id = f"{next_numeric_id(existing, 'dr')}_{idea_id}"
    request = f"""# Deep Research Request: {request_id}

## Idea
{idea.get('raw_text', '')}

## Project context
{project_brief or 'No project brief found.'}

## Idea metadata
- Status: `{idea.get('status', '')}`
- Priority: `{idea.get('priority', '')}`
- Confidence: `{idea.get('confidence', '')}`
- Rationale: {idea.get('rationale', '') or 'none'}
- Current evidence: {idea.get('current_evidence', '') or 'none'}

## Relevant run and cycle evidence
{cycle_notes or 'No cycle evidence yet.'}

{reviewer_notes or 'No run reviewer evidence yet.'}

## Leaderboard and best by direction
{leaderboard}

## Wiki and paper database summaries
{wiki_index or 'No wiki summary yet.'}

Paper DB:
{format_papers(papers)}

## Current architecture / workflow
{repo_architecture_summary(paths)}

## Scheduler and resource constraints
{scheduler or 'No scheduler budget found.'}

## Open questions
{open_questions or 'none'}

## Revised plans and reviewer opinions
See the evidence sections above. Prioritize explicit reviewer verdicts and revised plans over raw ideas.

## Requested output
Return actionable next experiments, risks, relevant papers/repos/weights, evidence gaps, and citations. Distinguish science, workflow, repo, and benchmark implications.
"""
    path = paths.research / "deep_requests" / f"{request_id}.md"
    write_text(path, request)
    record = {
        "request_id": request_id,
        "created_at": utc_now(),
        "reason": f"idea:{idea_id}",
        "blocking": False,
        "status": "created",
        "request_path": str(path),
        "result_path": "",
        "linked_cycle_ids": [],
        "linked_run_ids": [],
        "linked_idea_ids": [idea_id],
        "linked_revised_plan": "",
        "ingested_at": "",
        "wiki_updates": [],
        "decision_impact": "",
        "kind": "science",
    }
    append_jsonl(paths.research / "deep_requests" / "registry.jsonl", record)
    update_idea(
        paths,
        idea_id,
        status="needs_deep_research",
        linked_deep_request_id=request_id,
        next_action=f"wait for deep research result for {request_id}",
    )
    record_event(paths, "deep_research_request_created", f"From idea {idea_id}", status="nonblocking", payload=record)
    return request_id


def collect_existing_text(root, names: list[str], *, limit: int) -> str:
    snippets: list[str] = []
    if not root.exists():
        return ""
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        for name in names:
            path = directory / name
            if path.exists() and path.read_text().strip():
                snippets.append(f"### {directory.name}/{name}\n{path.read_text()[-3000:]}")
    return "\n\n".join(snippets)[-limit:]


def format_papers(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "No paper records yet."
    return "\n".join(f"- `{row.get('paper_id', '')}` {row.get('title', '')} ({row.get('year', '')}) status={row.get('status', '')}" for row in rows)


def repo_architecture_summary(paths: VibePaths) -> str:
    pyproject = paths.root / "pyproject.toml"
    files = sorted(path.name for path in paths.root.iterdir() if path.is_file())[:30] if paths.root.exists() else []
    package_dirs = sorted(path.name for path in paths.root.iterdir() if path.is_dir() and (path / "__init__.py").exists())[:20] if paths.root.exists() else []
    summary = [f"Target repository: `{paths.root}`", f"Top-level files: {', '.join(files) or 'none'}", f"Python package dirs: {', '.join(package_dirs) or 'none'}"]
    if pyproject.exists():
        summary.append("pyproject.toml excerpt:\n" + pyproject.read_text()[:4000])
    return "\n".join(summary)


def sync_plan_idea_updates(paths: VibePaths, text: str) -> None:
    """Apply simple `- idea_001: status` lines from an Idea pool update section."""

    if "## Idea pool update" not in text:
        return
    section = text.split("## Idea pool update", 1)[1]
    for line in section.splitlines():
        clean = line.strip("-* \t")
        if not clean.startswith("idea_") or ":" not in clean:
            continue
        idea_id, status_text = clean.split(":", 1)
        status = status_text.strip().split()[0]
        if status in IDEA_STATUSES:
            try:
                update_idea(paths, idea_id.strip(), status=status, next_action=f"synced from revised plan: {status}")
            except ValueError:
                continue


def render_idea_views(paths: VibePaths, ideas: list[dict[str, Any]] | None = None) -> None:
    ensure_idea_pool(paths)
    rows = ideas if ideas is not None else read_jsonl(paths.ideas / "registry.jsonl")
    for filename, statuses in IDEA_FILES.items():
        lines = [f"# {title_for_file(filename)}", ""]
        selected = [row for row in rows if row.get("status", "new") in statuses]
        if not selected:
            lines.append("No ideas yet.")
        else:
            lines.extend(["| Idea | Status | Priority | Confidence | Next action | Text |", "|---|---|---|---|---|---|"])
            for row in selected:
                lines.append(
                    f"| `{row.get('idea_id', '')}` | `{row.get('status', '')}` | `{row.get('priority', '')}` | "
                    f"`{row.get('confidence', '')}` | {row.get('next_action', '')} | {row.get('raw_text', '')[:160]} |"
                )
        write_text(paths.ideas / filename, "\n".join(lines) + "\n")
