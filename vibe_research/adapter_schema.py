"""Adapter manifest schema, linting, and revision helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from .decisions import DecisionType
from .io import read_yaml, utc_now, write_yaml
from .paths import VibePaths


CapabilityStatus = Literal[
    "candidate",
    "draft",
    "active",
    "blocked_missing_script",
    "blocked_missing_metrics_schema",
    "blocked_missing_user_answer",
    "deprecated",
]
MaturityLevel = Literal[
    "missing",
    "draft",
    "instrumentation_bootstrap",
    "evaluation_ready",
    "training_ready",
    "baseline_compare_ready",
    "long_run_ready",
]


class AdapterQuestion(BaseModel):
    id: str
    question: str
    why_needed: str = ""
    blocks_capability: str = ""
    blocks_field: str = ""
    severity: Literal["blocker", "non_blocker"] = "blocker"
    current_answer: str = ""
    answer_source: str = ""
    confirmed: bool = False
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class MetricsSchema(BaseModel):
    required: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)
    types: dict[str, str] = Field(default_factory=dict)
    direction: dict[str, str] = Field(default_factory=dict)
    units: dict[str, str] = Field(default_factory=dict)
    primary_metric: str = "primary"
    secondary_metrics: list[str] = Field(default_factory=list)
    comparison_rule: str = "higher_is_better"
    valid_range: dict[str, list[float]] = Field(default_factory=dict)
    missing_behavior: str = "untrusted"
    version: str = "draft"


class ArtifactRules(BaseModel):
    expected_outputs: list[str] = Field(default_factory=list)
    trusted_path_patterns: list[str] = Field(default_factory=list)
    required_files: list[str] = Field(default_factory=list)
    optional_files: list[str] = Field(default_factory=list)
    log_paths: list[str] = Field(default_factory=list)
    checkpoint_paths: list[str] = Field(default_factory=list)
    evaluation_output_paths: list[str] = Field(default_factory=list)
    reports: list[str] = Field(default_factory=list)
    retention_policy: str = "project_default"
    baseline_target_provenance: str = ""
    version: str = "draft"


class ResourcePolicy(BaseModel):
    resource_type: str = "cpu"
    automatic_submission_allowed: bool = False
    default: dict[str, Any] = Field(default_factory=lambda: {"gpu": 0, "cpus": 1, "mem_gb": 1, "time": "00:05:00"})
    maximum: dict[str, Any] = Field(default_factory=dict)
    long_run_allowed: bool = False
    user_confirmation_required: bool = True
    allowed_backends: list[str] = Field(default_factory=lambda: ["local"])
    dryrun: dict[str, Any] = Field(default_factory=dict)
    smoke: dict[str, Any] = Field(default_factory=dict)
    full_run: dict[str, Any] = Field(default_factory=dict)


class AdapterCapability(BaseModel):
    id: str
    version: str = "draft"
    status: CapabilityStatus = "draft"
    task_type: str = ""
    supported_decisions: list[DecisionType] = Field(default_factory=list)
    description: str = ""
    dryrun: dict[str, Any] = Field(default_factory=dict)
    entrypoint: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    metrics_schema: MetricsSchema = Field(default_factory=MetricsSchema)
    artifact_rules: ArtifactRules = Field(default_factory=ArtifactRules)
    resources: ResourcePolicy = Field(default_factory=ResourcePolicy)
    trust_checks: list[str] = Field(default_factory=list)
    contract_tests: list[str] = Field(default_factory=list)
    failure_modes: list[str] = Field(default_factory=list)
    block_conditions: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    owner_notes: str = ""
    activation: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_active_contract(self) -> "AdapterCapability":
        if self.status == "active":
            missing = active_capability_missing_fields(self)
            if missing:
                raise ValueError("active capability missing required fields: " + ", ".join(missing))
        return self


class AdapterManifest(BaseModel):
    adapter_version: str = "0.7.1"
    adapter_revision: str = ""
    project_id: str = ""
    project_name: str = ""
    project_summary: str = ""
    research_objective: str = ""
    data_access_notes: str = ""
    baseline_notes: str = ""
    capabilities: list[AdapterCapability] = Field(default_factory=list)
    metrics_schemas: dict[str, MetricsSchema] = Field(default_factory=dict)
    artifact_rules: dict[str, ArtifactRules] = Field(default_factory=dict)
    resource_policies: dict[str, ResourcePolicy] = Field(default_factory=dict)
    safety_policies: dict[str, Any] = Field(default_factory=dict)
    open_questions: list[AdapterQuestion] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    maturity_level: MaturityLevel = "draft"


def active_capability_missing_fields(capability: AdapterCapability) -> list[str]:
    missing: list[str] = []
    if not capability.dryrun.get("command"):
        missing.append("dryrun.command")
    if not capability.entrypoint.get("command"):
        missing.append("entrypoint.command")
    if not capability.metrics_schema.required and not capability.metrics_schema.types:
        missing.append("metrics_schema")
    if not capability.artifact_rules.expected_outputs and not capability.outputs.get("expected_output_path"):
        missing.append("artifact_rules.expected_outputs")
    if not capability.resources.default:
        missing.append("resources.default")
    if not capability.trust_checks:
        missing.append("trust_checks")
    if not capability.contract_tests:
        missing.append("contract_tests")
    return missing


def adapter_path(paths: VibePaths) -> Any:
    return paths.vibe / "adapter.yaml"


def load_adapter_manifest(paths: VibePaths) -> AdapterManifest:
    data = read_yaml(adapter_path(paths), {})
    if not isinstance(data, dict):
        data = {}
    try:
        return AdapterManifest.model_validate(data)
    except ValidationError:
        # Lint reports schema errors; callers that need a partial view still get
        # a permissive draft manifest.
        default = AdapterManifest().model_dump()
        capabilities = [
            partial_capability(cap)
            for cap in data.get("capabilities", [])
            if isinstance(cap, dict)
        ]
        questions = [
            partial_question(question)
            for question in data.get("open_questions", [])
            if isinstance(question, dict)
        ]
        return AdapterManifest.model_construct(**{**default, **data, "capabilities": capabilities, "open_questions": questions})


def partial_capability(data: dict[str, Any]) -> AdapterCapability:
    cap_id = str(data.get("id") or "unknown")
    try:
        return AdapterCapability.model_validate(data)
    except ValidationError:
        base = AdapterCapability(id=cap_id).model_dump()
        merged = {**base, **data}
        if isinstance(merged.get("metrics_schema"), dict):
            merged["metrics_schema"] = partial_model(MetricsSchema, merged["metrics_schema"])
        if isinstance(merged.get("artifact_rules"), dict):
            merged["artifact_rules"] = partial_model(ArtifactRules, merged["artifact_rules"])
        if isinstance(merged.get("resources"), dict):
            merged["resources"] = partial_model(ResourcePolicy, merged["resources"])
        return AdapterCapability.model_construct(**merged)


def partial_question(data: dict[str, Any]) -> AdapterQuestion:
    try:
        return AdapterQuestion.model_validate(data)
    except ValidationError:
        base = AdapterQuestion(id=str(data.get("id") or "unknown"), question=str(data.get("question") or "Unspecified question")).model_dump()
        return AdapterQuestion.model_construct(**{**base, **data})


def partial_model(model: type[BaseModel], data: dict[str, Any]) -> BaseModel:
    try:
        return model.model_validate(data)
    except ValidationError:
        return model.model_construct(**{**model().model_dump(), **data})


def write_adapter_manifest(paths: VibePaths, manifest: AdapterManifest) -> None:
    manifest.adapter_revision = compute_revision(manifest.model_dump(exclude={"adapter_revision"}))
    manifest.maturity_level = derive_maturity(manifest)
    write_yaml(adapter_path(paths), manifest.model_dump())


def compute_revision(data: Any) -> str:
    raw = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def hash_dict(data: Any) -> str:
    return compute_revision(data)


def derive_maturity(manifest: AdapterManifest) -> MaturityLevel:
    active = {cap.task_type for cap in manifest.capabilities if cap.status == "active"}
    if not manifest.capabilities:
        return "draft"
    if "long_run_submit" in active:
        return "long_run_ready"
    if "baseline_compare" in active:
        return "baseline_compare_ready"
    if any(task in active for task in ["train_gate", "train_smoke"]):
        return "training_ready"
    if any(task in active for task in ["evaluation_smoke", "metrics_export"]):
        return "evaluation_ready"
    if active:
        return "instrumentation_bootstrap"
    return "draft"


def lint_adapter(paths: VibePaths) -> dict[str, Any]:
    raw = read_yaml(adapter_path(paths), {})
    errors: list[str] = []
    warnings: list[str] = []
    manifest: AdapterManifest
    if not raw:
        return {
            "ok": False,
            "errors": ["missing .vibe/adapter.yaml"],
            "warnings": [],
            "maturity_level": "missing",
            "active_capabilities": [],
            "blocked_capabilities": [],
            "draft_capabilities": [],
            "questions": [],
            "checked_at": utc_now(),
        }
    try:
        manifest = AdapterManifest.model_validate(raw)
    except ValidationError as exc:
        errors.extend(f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in exc.errors())
        manifest = load_adapter_manifest(paths)
    for cap in manifest.capabilities:
        if cap.status == "active":
            missing = active_capability_missing_fields(cap)
            if missing:
                errors.append(f"{cap.id}: active capability missing {', '.join(missing)}")
            if cap.activation.get("contract_status") != "passed":
                errors.append(f"{cap.id}: active capability lacks passed contract test activation")
        elif cap.status in {"candidate", "draft"}:
            missing = active_capability_missing_fields(cap)
            if missing:
                warnings.append(f"{cap.id}: draft not schedulable, missing {', '.join(missing)}")
        if cap.status not in {"candidate", "draft", "active", "blocked_missing_script", "blocked_missing_metrics_schema", "blocked_missing_user_answer", "deprecated"}:
            errors.append(f"{cap.id}: invalid status {cap.status}")
        if cap.supported_decisions and not all(isinstance(item, str) for item in cap.supported_decisions):
            errors.append(f"{cap.id}: supported_decisions must be strings")
    active_caps = [cap.id for cap in manifest.capabilities if cap.status == "active"]
    blocked = [cap.id for cap in manifest.capabilities if cap.status.startswith("blocked_")]
    draft = [cap.id for cap in manifest.capabilities if cap.status in {"candidate", "draft"}]
    lint = {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "maturity_level": derive_maturity(manifest),
        "adapter_revision": manifest.adapter_revision or compute_revision(raw),
        "active_capabilities": active_caps,
        "blocked_capabilities": blocked,
        "draft_capabilities": draft,
        "questions": [q.model_dump() for q in manifest.open_questions],
        "checked_at": utc_now(),
    }
    return lint
