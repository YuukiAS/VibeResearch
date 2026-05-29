"""Artifact validation and hard-rule gates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .codex_adapter import artifact_path
from .io import read_json, read_jsonl
from .paths import VibePaths


@dataclass
class ArtifactIssue:
    level: str
    message: str


REQUIRED_SECTIONS = {
    "portfolio_planner": [
        "## Stage",
        "## Current leaderboard summary",
        "## User ideas and directives considered",
        "## Candidate directions",
        "## Selected runs",
        "## Dependency graph",
        "## Resource budget",
        "## Portfolio success criteria",
        "## Stop or shrink criteria",
    ],
    "portfolio_reviewer": ["Verdict:"],
    "reviewer": ["Verdict:"],
    "reflect": ["## Result interpretation"],
    "revised_plan": [
        "## Result interpretation",
        "## Decision",
        "## Plan update",
        "## Required changes",
        "## Evidence needed",
        "## Literature refresh decision",
        "## Deep research decision",
        "## Portfolio implication",
        "## Next experiment proposal",
        "## Stop condition",
    ],
    "cycle_reflect": ["## Run comparison"],
    "cycle_revised_plan": [
        "## Cycle-level interpretation",
        "## Direction decisions",
        "## Portfolio mode update",
        "## Next portfolio sketch",
        "## Resource update",
        "## Literature and deep research decision",
        "## User decision needed",
        "## Stop condition",
    ],
    "deep_research_request": [
        "## Project context",
        "## Current experimental evidence",
        "## Existing local knowledge",
        "## Core research question",
        "## Required comparisons",
        "## What counts as useful output",
        "## What to avoid",
        "## Expected deliverable",
    ],
}


def validate_artifact(paths: VibePaths, role: str, target_id: str) -> list[ArtifactIssue]:
    path = artifact_path(paths, role, target_id)
    if not path.exists():
        return [ArtifactIssue("error", f"missing artifact: {path}")]
    text = path.read_text()
    issues: list[ArtifactIssue] = []
    if not text.strip():
        issues.append(ArtifactIssue("error", f"empty artifact: {path}"))
    for section in REQUIRED_SECTIONS.get(role, []):
        if section not in text:
            issues.append(ArtifactIssue("error", f"missing required section `{section}` in {path.name}"))
    return issues


def validate_hard_rules(paths: VibePaths) -> list[ArtifactIssue]:
    """Check TODO.md section 22 hard rules for current state."""

    state = read_json(paths.state / "state.json", {})
    issues: list[ArtifactIssue] = []
    for cycle_id in state.get("cycles", {}):
        cycle_dir = paths.cycles / cycle_id
        for name in ["portfolio_plan.md", "portfolio_review.md", "resource_plan.yaml"]:
            if not (cycle_dir / name).exists():
                issues.append(ArtifactIssue("error", f"{cycle_id} missing {name}"))
        if state.get("cycles", {}).get(cycle_id, {}).get("status") in {"revised", "completed"}:
            for name in ["cycle_reflect.md", "cycle_revised_plan.md"]:
                if not has_text(cycle_dir / name):
                    issues.append(ArtifactIssue("error", f"{cycle_id} missing {name}"))
    for run_id, run in state.get("runs", {}).items():
        run_dir = paths.runs / run_id
        for name in ["proposal.md", "review.md", "manifest.json", "patch.diff", "branch.txt"]:
            if not (run_dir / name).exists():
                issues.append(ArtifactIssue("error", f"{run_id} missing {name}"))
        if run.get("status") in {"collected", "reflected", "revised", "merged"} and not has_text(run_dir / "metrics.json"):
            issues.append(ArtifactIssue("error", f"{run_id} missing metrics.json"))
        if run.get("status") in {"reflected", "revised", "merged"} and not has_text(run_dir / "reflect.md"):
            issues.append(ArtifactIssue("error", f"{run_id} missing reflect.md"))
        if run.get("status") in {"revised", "merged"} and not has_text(run_dir / "revised_plan.md"):
            issues.append(ArtifactIssue("error", f"{run_id} missing revised_plan.md"))
    for row in read_jsonl(paths.leaderboard / "history.jsonl"):
        if row.get("trusted") and not row.get("provenance"):
            issues.append(ArtifactIssue("error", f"trusted leaderboard row lacks provenance: {row.get('run_id')}"))
    return issues


def has_text(path: Path) -> bool:
    return path.exists() and bool(path.read_text().strip())

