"""Artifact validation and hard-rule gates."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3

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
        "## Idea pool update",
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
        "## Idea pool update",
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
        "## Idea pool update",
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

SECTION_ALIASES = {
    ("reflect", "## Result interpretation"): {
        "## Result Interpretation",
        "## Completed Result Interpretation",
    }
}

PORTFOLIO_VERDICTS = {"APPROVE_PORTFOLIO", "APPROVE_WITH_RESOURCE_GUARDS", "REVISE_PORTFOLIO", "BLOCK_PORTFOLIO"}
RUN_VERDICTS = {"APPROVE", "APPROVE_WITH_GUARDS", "REVISE_OR_BLOCK"}
REVISED_DECISIONS = {
    "continue_same_plan",
    "modify_experiment",
    "run_ablation",
    "repeat_seed",
    "collect_more_metrics",
    "literature_refresh_needed",
    "deep_research_needed",
    "stop_branch",
    "merge_candidate",
    "ask_user",
    "blocked_missing_decision",
    "blocked_missing_adapter",
    "blocked_missing_resource_plan",
    "blocked_repeating_evidence",
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
        if not has_required_section(text, role, section):
            issues.append(ArtifactIssue("error", f"missing required section `{section}` in {path.name}"))
    if role == "portfolio_reviewer":
        verdict = extract_value(text, "Verdict:")
        if verdict and verdict not in PORTFOLIO_VERDICTS:
            issues.append(ArtifactIssue("error", f"invalid portfolio verdict `{verdict}`"))
    if role == "reviewer":
        verdict = extract_value(text, "Verdict:")
        if verdict and verdict not in RUN_VERDICTS:
            issues.append(ArtifactIssue("error", f"invalid run verdict `{verdict}`"))
    if role == "revised_plan":
        decision = extract_section_first_value(text, "## Decision")
        if decision and decision not in REVISED_DECISIONS:
            issues.append(ArtifactIssue("error", f"invalid revised-plan decision `{decision}`"))
        for label in ["## Literature refresh decision", "## Deep research decision"]:
            value = extract_section_first_value(text, label).lower()
            if value and not value.startswith(("yes", "no")):
                issues.append(ArtifactIssue("error", f"{label} must start with yes or no"))
    if role == "cycle_revised_plan":
        value = extract_section_first_value(text, "## Literature and deep research decision").lower()
        if value and "literature" not in value and "deep research" not in value:
            issues.append(ArtifactIssue("warning", "cycle revised plan should mention literature and deep research decisions"))
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
        review_text = (cycle_dir / "portfolio_review.md").read_text() if (cycle_dir / "portfolio_review.md").exists() else ""
        verdict = extract_value(review_text, "Verdict:")
        if verdict in {"BLOCK_PORTFOLIO", "REVISE_PORTFOLIO"}:
            for run_id, run in state.get("runs", {}).items():
                if run.get("cycle_id") == cycle_id and run.get("status") not in {"generated", "abandoned"}:
                    issues.append(ArtifactIssue("error", f"{run_id} advanced after portfolio verdict {verdict}"))
        if state.get("cycles", {}).get(cycle_id, {}).get("status") in {"revised", "completed"}:
            for name in ["cycle_reflect.md", "cycle_revised_plan.md"]:
                if not has_text(cycle_dir / name):
                    issues.append(ArtifactIssue("error", f"{cycle_id} missing {name}"))
        if state.get("cycles", {}).get(cycle_id, {}).get("status") in {"revised", "blocked"} and not has_text(cycle_dir / "cycle_decision.json"):
            issues.append(ArtifactIssue("error", f"{cycle_id} missing cycle_decision.json"))
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
        if run.get("status") in {"revised", "blocked", "merged"} and not has_text(run_dir / "decision.json"):
            issues.append(ArtifactIssue("error", f"{run_id} missing decision.json"))
        if run.get("status") == "merged" and run.get("merge_review") != "MERGE_OK":
            issues.append(ArtifactIssue("error", f"{run_id} merged without MERGE_OK"))
        launch = read_json(run_dir / "launch.json", {})
        if launch and launch.get("backend") == "slurm":
            for key in ["job_id", "partition", "log_path", "resource_request"]:
                if not launch.get(key):
                    issues.append(ArtifactIssue("error", f"{run_id} slurm launch missing {key}"))
    for row in read_jsonl(paths.leaderboard / "history.jsonl"):
        if row.get("trusted") and not row.get("provenance"):
            issues.append(ArtifactIssue("error", f"trusted leaderboard row lacks provenance: {row.get('run_id')}"))
    for row in read_jsonl(paths.research / "deep_requests" / "registry.jsonl"):
        if row.get("blocking") and row.get("status") != "ingested":
            if not row.get("request_path"):
                issues.append(ArtifactIssue("error", f"blocking deep research lacks request path: {row.get('request_id')}"))
    paper_db = paths.research / "papers.sqlite"
    if paper_db.exists():
        try:
            conn = sqlite3.connect(paper_db)
            for paper_id, status, source_url, local_pdf_path, sha256 in conn.execute("SELECT paper_id,status,source_url,local_pdf_path,sha256 FROM papers"):
                if status in {"downloaded", "ingested", "formal"}:
                    if not source_url and not local_pdf_path:
                        issues.append(ArtifactIssue("error", f"{paper_id} formal paper lacks source or local PDF"))
                    if local_pdf_path and not sha256:
                        issues.append(ArtifactIssue("error", f"{paper_id} local PDF lacks checksum"))
            conn.close()
        except Exception as exc:
            issues.append(ArtifactIssue("warning", f"paper DB validation skipped: {exc}"))
    return issues


def has_text(path: Path) -> bool:
    return path.exists() and bool(path.read_text().strip())


def has_required_section(text: str, role: str, section: str) -> bool:
    if section in text:
        return True
    return any(alias in text for alias in SECTION_ALIASES.get((role, section), set()))


def extract_value(text: str, label: str) -> str:
    for line in text.splitlines():
        if line.strip().startswith(label):
            return line.split(label, 1)[1].strip().split()[0] if line.split(label, 1)[1].strip() else ""
    return ""


def extract_section_first_value(text: str, section: str) -> str:
    if section not in text:
        return ""
    body = text.split(section, 1)[1]
    if "\n## " in body:
        body = body.split("\n## ", 1)[0]
    for line in body.splitlines():
        value = line.strip().strip("-*` ")
        if value:
            return value.split()[0]
    return ""
