"""Scout quality gates, triage, and claim-evidence mapping."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from .io import append_jsonl, ensure_dir, next_numeric_id, read_json, read_jsonl, utc_now, write_json, write_text
from .paths import VibePaths
from .research_manager import load_hypotheses


SCOUT_CATEGORIES = {
    "background",
    "candidate_method",
    "directly_actionable",
    "baseline_reference",
    "negative_evidence",
    "implementation_reference",
    "not_relevant",
}
ACTIONABLE_CATEGORIES = {"directly_actionable", "baseline_reference", "implementation_reference"}


class ScoutFindingRecord(BaseModel):
    finding_id: str
    source_type: str = "paper"
    title: str
    authors_or_repo: str = ""
    year: str = ""
    url_or_ref: str = ""
    task_match: float = 0.0
    dataset_match: float = 0.0
    metric_match: float = 0.0
    method_match: float = 0.0
    failure_mode_match: float = 0.0
    actionability: float = 0.0
    novelty: float = 0.0
    credibility: float = 0.0
    has_code: bool = False
    reproducible_experiment: bool = False
    hypothesis_id: str = ""
    relationship_to_hypothesis: str = ""
    possible_experiment: str = ""
    risks: list[str] = Field(default_factory=list)
    counterevidence: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    summary: str = ""
    created_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_scores(self) -> "ScoutFindingRecord":
        for key in [
            "task_match",
            "dataset_match",
            "metric_match",
            "method_match",
            "failure_mode_match",
            "actionability",
            "novelty",
            "credibility",
            "confidence",
        ]:
            value = getattr(self, key)
            if value < 0 or value > 1:
                raise ValueError(f"{key} must be between 0 and 1")
        return self


class ScoutTriageRecord(BaseModel):
    triage_id: str
    finding_id: str
    category: str
    relevance_score: float
    specificity_score: float
    actionability_score: float
    novelty_score: float
    credibility_score: float
    rationale: str
    allowed_for_experiment: bool
    allowed_for_internalization: bool
    created_at: str = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_category(self) -> "ScoutTriageRecord":
        if self.category not in SCOUT_CATEGORIES:
            raise ValueError(f"unsupported scout category: {self.category}")
        return self


class ScoutClaimRecord(BaseModel):
    claim_id: str
    claim: str
    support_finding_ids: list[str] = Field(default_factory=list)
    oppose_finding_ids: list[str] = Field(default_factory=list)
    applicability: str = ""
    transfer_limits: str = ""
    suggested_experiment: str = ""
    confidence: float = 0.0
    created_at: str = Field(default_factory=utc_now)


class MechanismCardRecord(BaseModel):
    card_id: str
    source_type: str = "paper"
    source: str
    claim: str
    mechanism_extraction: str
    why_it_matters: str
    failure_anchor: str
    possible_mve: str = ""
    required_assets: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    stop_reason: str
    status: str = "PLAN_CANDIDATE"
    card_path: str = ""
    created_at: str = Field(default_factory=utc_now)


def scout_dir(paths: VibePaths):
    return ensure_dir(paths.research / "scout")


def scout_paths(paths: VibePaths) -> dict[str, Any]:
    base = scout_dir(paths)
    return {
        "findings": base / "findings.jsonl",
        "triage": base / "triage.jsonl",
        "claims": base / "claims.jsonl",
        "negative": base / "negative_evidence.jsonl",
        "queries": base / "queries.jsonl",
        "mechanism_cards": base / "mechanism_cards",
        "mechanism_registry": base / "mechanism_cards.jsonl",
        "audit": base / "audit.json",
        "memo": base / "memo.md",
    }


def add_scout_finding(paths: VibePaths, **kwargs: Any) -> dict[str, Any]:
    files = scout_paths(paths)
    existing = [row.get("finding_id", "") for row in read_jsonl(files["findings"])]
    record = ScoutFindingRecord(finding_id=next_numeric_id(existing, "scout_"), **kwargs).model_dump()
    append_jsonl(files["findings"], record)
    return record


def triage_scout_finding(paths: VibePaths, finding_id: str, *, rationale: str = "") -> dict[str, Any]:
    files = scout_paths(paths)
    finding = next((row for row in read_jsonl(files["findings"]) if row.get("finding_id") == finding_id), None)
    if not finding:
        raise ValueError(f"Unknown scout finding: {finding_id}")
    triages = read_jsonl(files["triage"])
    category, default_rationale = classify_finding(finding)
    relevance = average([finding.get("task_match", 0), finding.get("dataset_match", 0), finding.get("metric_match", 0)])
    specificity = average([finding.get("method_match", 0), finding.get("failure_mode_match", 0), finding.get("dataset_match", 0)])
    record = ScoutTriageRecord(
        triage_id=next_numeric_id([row.get("triage_id", "") for row in triages], "triage_"),
        finding_id=finding_id,
        category=category,
        relevance_score=relevance,
        specificity_score=specificity,
        actionability_score=float(finding.get("actionability", 0) or 0),
        novelty_score=float(finding.get("novelty", 0) or 0),
        credibility_score=float(finding.get("credibility", 0) or 0),
        rationale=rationale or default_rationale,
        allowed_for_experiment=category in ACTIONABLE_CATEGORIES,
        allowed_for_internalization=category in ACTIONABLE_CATEGORIES,
    ).model_dump()
    append_jsonl(files["triage"], record)
    if category == "negative_evidence":
        append_jsonl(files["negative"], {"finding_id": finding_id, "created_at": utc_now(), "risks": finding.get("risks", []), "counterevidence": finding.get("counterevidence", []), "rationale": record["rationale"]})
    return record


def classify_finding(finding: dict[str, Any]) -> tuple[str, str]:
    relevance = average([finding.get("task_match", 0), finding.get("dataset_match", 0), finding.get("metric_match", 0)])
    specificity = average([finding.get("method_match", 0), finding.get("failure_mode_match", 0), finding.get("dataset_match", 0)])
    actionability = float(finding.get("actionability", 0) or 0)
    credibility = float(finding.get("credibility", 0) or 0)
    has_code = bool(finding.get("has_code") or finding.get("reproducible_experiment"))
    relation = str(finding.get("relationship_to_hypothesis", "")).lower()
    if relevance < 0.25 or credibility < 0.2:
        return "not_relevant", "low relevance or credibility"
    if finding.get("counterevidence") or "negative" in relation or "failure" in relation:
        return "negative_evidence", "finding mainly records negative evidence or limits"
    if "baseline" in relation:
        return "baseline_reference", "finding can serve as a baseline reference"
    if has_code and specificity >= 0.55 and actionability >= 0.55:
        return "implementation_reference", "specific and reproducible implementation reference"
    if relevance >= 0.65 and specificity >= 0.65 and actionability >= 0.65 and credibility >= 0.6:
        return "directly_actionable", "specific, credible, and actionable for a concrete experiment"
    if relevance >= 0.5 and specificity >= 0.45 and credibility >= 0.55:
        return "candidate_method", "credible method evidence that needs local design before execution"
    return "background", "relevant background but not enough to trigger an experiment"


def create_scout_claim(
    paths: VibePaths,
    *,
    claim: str,
    support_finding_ids: list[str] | None = None,
    oppose_finding_ids: list[str] | None = None,
    applicability: str = "",
    transfer_limits: str = "",
    suggested_experiment: str = "",
    confidence: float = 0.0,
) -> dict[str, Any]:
    files = scout_paths(paths)
    existing = [row.get("claim_id", "") for row in read_jsonl(files["claims"])]
    record = ScoutClaimRecord(
        claim_id=next_numeric_id(existing, "claim_"),
        claim=claim,
        support_finding_ids=support_finding_ids or [],
        oppose_finding_ids=oppose_finding_ids or [],
        applicability=applicability,
        transfer_limits=transfer_limits,
        suggested_experiment=suggested_experiment,
        confidence=confidence,
    ).model_dump()
    append_jsonl(files["claims"], record)
    return record


def create_mechanism_card(
    paths: VibePaths,
    *,
    source: str,
    claim: str,
    mechanism_extraction: str,
    why_it_matters: str,
    failure_anchor: str,
    possible_mve: str = "",
    required_assets: list[str] | None = None,
    risks: list[str] | None = None,
    stop_reason: str,
    source_type: str = "paper",
) -> dict[str, Any]:
    files = scout_paths(paths)
    existing = [row.get("card_id", "") for row in read_jsonl(files["mechanism_registry"])]
    card_id = next_numeric_id(existing, "card_")
    status = "PLAN_CANDIDATE" if possible_mve.strip() else "ARCHIVED_NO_MVE"
    card_dir = ensure_dir(files["mechanism_cards"] / card_id)
    card_path = card_dir / "mechanism_card.md"
    record = MechanismCardRecord(
        card_id=card_id,
        source_type=source_type,
        source=source,
        claim=claim,
        mechanism_extraction=mechanism_extraction,
        why_it_matters=why_it_matters,
        failure_anchor=failure_anchor,
        possible_mve=possible_mve,
        required_assets=required_assets or [],
        risks=risks or [],
        stop_reason=stop_reason,
        status=status,
        card_path=str(card_path.relative_to(paths.root)),
    ).model_dump()
    write_text(card_path, render_mechanism_card(record))
    write_json(card_dir / "mechanism_card.json", record)
    append_jsonl(files["mechanism_registry"], record)
    return record


def render_mechanism_card(card: dict[str, Any]) -> str:
    assets = "\n".join(f"- {item}" for item in card.get("required_assets", [])) or "- none"
    risks = "\n".join(f"- {item}" for item in card.get("risks", [])) or "- none"
    return "\n".join(
        [
            "# Mechanism Card",
            "",
            f"card_id: {card.get('card_id', '')}",
            f"status: {card.get('status', '')}",
            "",
            "## Source",
            f"{card.get('source_type', '')}: {card.get('source', '')}",
            "",
            "## Claim",
            str(card.get("claim", "")),
            "",
            "## Mechanism Extraction",
            str(card.get("mechanism_extraction", "")),
            "",
            "## Why It Matters",
            str(card.get("why_it_matters", "")),
            "",
            "## Failure Anchor",
            str(card.get("failure_anchor", "")),
            "",
            "## Possible MVE",
            str(card.get("possible_mve", "")),
            "",
            "## Required Assets",
            assets,
            "",
            "## Risks",
            risks,
            "",
            "## Stop Reason",
            str(card.get("stop_reason", "")),
            "",
        ]
    )


def validate_mechanism_card(card: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    for field in ("source", "claim", "mechanism_extraction", "why_it_matters", "failure_anchor", "stop_reason"):
        if not str(card.get(field, "")).strip():
            issues.append(f"{field} is required")
    if not str(card.get("possible_mve", "")).strip():
        issues.append("possible_mve is required before planning")
    if card.get("status") == "ARCHIVED_NO_MVE":
        issues.append("mechanism card is archived because it has no possible MVE")
    return issues


def load_mechanism_card(paths: VibePaths, card_id_or_path: str) -> dict[str, Any]:
    files = scout_paths(paths)
    for row in read_jsonl(files["mechanism_registry"]):
        if row.get("card_id") == card_id_or_path:
            return row
    path = paths.root / card_id_or_path
    if path.name == "mechanism_card.md":
        json_path = path.with_suffix(".json")
    else:
        json_path = path
    return read_json(json_path, {})


def scout_query_context(paths: VibePaths) -> dict[str, Any]:
    hypotheses = load_hypotheses(paths)
    lineage_memory = read_json(paths.research / "lineage" / "memory.json", {})
    open_questions = read_jsonl(paths.research / "questions.jsonl")
    rows = []
    for hyp in hypotheses.values():
        rows.append(
            {
                "hypothesis_id": hyp.get("hypothesis_id", ""),
                "query_seed": " ".join(
                    part
                    for part in [
                        hyp.get("title", ""),
                        hyp.get("next_testable_change", ""),
                        " ".join(hyp.get("target_metrics", [])),
                        " ".join(str(item) for item in hyp.get("negative_evidence", [])),
                    ]
                    if part
                ),
                "failure_analysis": hyp.get("failure_analysis", {}),
                "remaining_upside": hyp.get("remaining_upside", {}),
            }
        )
    record = {"created_at": utc_now(), "hypotheses": rows, "lineage_memory": lineage_memory, "open_questions": [row for row in open_questions if row.get("status", "open") == "open"]}
    append_jsonl(scout_paths(paths)["queries"], record)
    return record


def scout_audit(paths: VibePaths) -> dict[str, Any]:
    files = scout_paths(paths)
    findings = read_jsonl(files["findings"])
    triages = read_jsonl(files["triage"])
    claims = read_jsonl(files["claims"])
    category_counts: dict[str, int] = {}
    for row in triages:
        category_counts[row.get("category", "unknown")] = category_counts.get(row.get("category", "unknown"), 0) + 1
    result = {
        "created_at": utc_now(),
        "finding_count": len(findings),
        "triaged_count": len(triages),
        "claim_count": len(claims),
        "actionable_count": sum(1 for row in triages if row.get("category") in ACTIONABLE_CATEGORIES),
        "background_count": category_counts.get("background", 0),
        "negative_evidence_count": category_counts.get("negative_evidence", 0),
        "category_counts": category_counts,
        "progress_summary": {
            "background": [row.get("finding_id", "") for row in triages if row.get("category") == "background"],
            "actionable": [row.get("finding_id", "") for row in triages if row.get("category") in ACTIONABLE_CATEGORIES],
            "claims": [row.get("claim_id", "") for row in claims],
        },
    }
    write_json(files["audit"], result)
    write_text(files["memo"], render_scout_memo(result))
    return result


def qualifying_scout_evidence(paths: VibePaths, scout_ids: list[str]) -> list[dict[str, Any]]:
    if not scout_ids:
        return []
    ids = set(scout_ids)
    return [row for row in read_jsonl(scout_paths(paths)["triage"]) if row.get("finding_id") in ids and row.get("category") in ACTIONABLE_CATEGORIES]


def average(values: list[Any]) -> float:
    numbers = [float(value or 0) for value in values]
    return sum(numbers) / len(numbers) if numbers else 0.0


def render_scout_memo(audit: dict[str, Any]) -> str:
    return (
        "# Scout Memo\n\n"
        f"Background findings: `{audit.get('background_count', 0)}`\n\n"
        f"Actionable scout evidence: `{audit.get('actionable_count', 0)}`\n\n"
        f"Testable claims: `{audit.get('claim_count', 0)}`\n\n"
        f"Negative evidence records: `{audit.get('negative_evidence_count', 0)}`\n"
    )
