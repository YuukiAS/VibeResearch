"""Project adapter interface and built-in generic adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..adapter_schema import AdapterCapability, hash_dict, load_adapter_manifest
from ..config import load_config
from ..io import read_json, read_yaml
from ..paths import VibePaths


PLACEHOLDER_TOKENS = [
    "placeholder",
    "todo",
    "fill me",
    "replace me",
    "vibe run placeholder",
    "vibe dryrun placeholder",
]


@dataclass
class CompileResult:
    ok: bool
    plan: dict[str, Any] | None = None
    block_reason: str = ""
    block_type: str = "blocked_missing_resource_plan"


class BaseAdapter:
    kind = "base"

    def __init__(self, paths: VibePaths, config: dict[str, Any] | None = None):
        self.paths = paths
        self.config = config or {}

    def compile_decision(self, decision: Any, cycle_id: str) -> CompileResult:
        return CompileResult(False, block_reason="adapter does not implement compilation", block_type="blocked_missing_adapter")

    def metrics_schema(self) -> dict[str, Any]:
        return {}


class NoopAdapter(BaseAdapter):
    kind = "noop"

    def compile_decision(self, decision: Any, cycle_id: str) -> CompileResult:
        return CompileResult(False, block_reason="No project adapter is configured; cannot compile scientific experiments", block_type="blocked_missing_adapter")


class ConfigAdapter(BaseAdapter):
    kind = "config"

    def __init__(self, paths: VibePaths, config: dict[str, Any] | None = None):
        super().__init__(paths, config)
        adapter_path = paths.root / str(self.config.get("config_path", ".vibe/adapter.yaml"))
        self.adapter_config = read_yaml(adapter_path, {}) if adapter_path.exists() else {}

    def compile_decision(self, decision: Any, cycle_id: str) -> CompileResult:
        manifest = load_adapter_manifest(self.paths)
        if manifest.capabilities:
            return compile_from_active_capabilities(self.paths, cycle_id, decision, manifest)
        task = (self.adapter_config or {}).get("task", {})
        if not task:
            return CompileResult(False, block_reason="adapter manifest has no active capability for automated experiments", block_type="blocked_missing_capability")
        if not isinstance(task, dict):
            return CompileResult(False, block_reason="adapter config is missing task declaration")
        plan = resource_plan_from_task(cycle_id, decision, task)
        errors = validate_compiled_plan(plan)
        if errors:
            return CompileResult(False, block_reason="; ".join(errors))
        return CompileResult(True, plan=plan)

    def metrics_schema(self) -> dict[str, Any]:
        return (self.adapter_config or {}).get("metrics_schema", {})


class ToyAdapter(BaseAdapter):
    kind = "toy"

    def compile_decision(self, decision: Any, cycle_id: str) -> CompileResult:
        task = {
            "key": "toy-audit",
            "direction_id": getattr(decision, "selected_direction", "") or "d001_toy",
            "hypothesis": "Run a generic toy audit task with schema-valid metrics.",
            "dryrun_command": "python -c 'print(\"toy dryrun ok\")'",
            "entrypoint_command": "python -c 'import json, pathlib; p=pathlib.Path(\".vibe/toy_metrics.json\"); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps({\"primary\": 1.0}))'",
            "expected_output_path": ".vibe/toy_metrics.json",
            "metrics_file_path": ".vibe/toy_metrics.json",
            "metrics_schema": {"primary": "number"},
            "resources": {"gpu": 0, "cpus": 1, "mem_gb": 1, "time": "00:05:00", "preferred_partitions": ["debug"], "fallback_partitions": []},
            "trust_rules": {"require_metrics_schema": True, "allow_manual_metric": False},
        }
        plan = resource_plan_from_task(cycle_id, decision, task)
        return CompileResult(True, plan=plan)

    def metrics_schema(self) -> dict[str, Any]:
        return {"primary": "number"}


def get_adapter(paths: VibePaths) -> BaseAdapter:
    config = load_config(paths)
    adapter_config = config.get("adapter", {}) if isinstance(config.get("adapter"), dict) else {}
    kind = adapter_config.get("kind", "config")
    if kind == "toy":
        return ToyAdapter(paths, adapter_config)
    if kind == "config":
        return ConfigAdapter(paths, adapter_config)
    return NoopAdapter(paths, adapter_config)


def resource_plan_from_task(cycle_id: str, decision: Any, task: dict[str, Any]) -> dict[str, Any]:
    key = str(task.get("key") or "compiled-task")
    return {
        "cycle_id": cycle_id,
        "mode": "compiled",
        "decision_id": getattr(decision, "decision_id", ""),
        "runs": {
            key: {
                "priority": int(task.get("priority", 1)),
                "direction_id": task.get("direction_id") or getattr(decision, "selected_direction", "") or "d000_compiled",
                "hypothesis": task.get("hypothesis") or getattr(decision, "required_action", "") or key,
                "expected_learning": task.get("expected_learning") or task.get("hypothesis") or key,
                "cost": task.get("cost", "low"),
                "dryrun": {"command": task.get("dryrun_command", ""), "max_minutes": int(task.get("dryrun_max_minutes", 5))},
                "entrypoint": {"type": "local", "command": task.get("entrypoint_command", "")},
                "resources": task.get("resources", {}),
                "outputs": {"expected_output_path": task.get("expected_output_path", "")},
                "evaluation": {
                    "metrics_file_path": task.get("metrics_file_path", ""),
                    "metrics_schema": task.get("metrics_schema", {}),
                    "trust_rules": task.get("trust_rules", {}),
                    "baseline_comparison_target": getattr(decision, "baseline_comparison_target", "") or task.get("baseline_comparison_target", ""),
                },
                "adapter_metadata": task.get("adapter_metadata", {}),
                "depends_on": list(task.get("depends_on", [])),
                "cancel_if_failed": list(task.get("cancel_if_failed", [])),
            }
        },
        "cancel_rules": list(task.get("cancel_rules", [])),
    }


def compile_from_active_capabilities(paths: VibePaths, cycle_id: str, decision: Any, manifest: Any) -> CompileResult:
    matches = [
        cap
        for cap in manifest.capabilities
        if getattr(cap, "status", "") == "active" and getattr(decision, "decision_type", "") in getattr(cap, "supported_decisions", [])
    ]
    if not matches:
        return CompileResult(False, block_reason=f"No active adapter capability supports {getattr(decision, 'decision_type', '')}", block_type="blocked_missing_capability")
    capability = choose_capability(matches, decision)
    missing = capability_block_reason(paths, capability, decision)
    if missing:
        return CompileResult(False, block_reason=missing[1], block_type=missing[0])
    task = task_from_capability(manifest, capability, decision)
    plan = resource_plan_from_task(cycle_id, decision, task)
    errors = validate_compiled_plan(plan)
    if errors:
        return CompileResult(False, block_reason="; ".join(errors), block_type="blocked_missing_resource_plan")
    return CompileResult(True, plan=plan)


def choose_capability(caps: list[AdapterCapability], decision: Any) -> AdapterCapability:
    # Deterministic selection. Prefer explicit selected direction matches, then
    # lower resource demand, then id for stable plans.
    selected = getattr(decision, "selected_direction", "")
    if selected:
        for cap in caps:
            if cap.id == selected or cap.task_type == selected:
                return cap
    return sorted(caps, key=lambda cap: (int(cap.resources.default.get("gpu", 0) or 0), cap.id))[0]


def capability_block_reason(paths: VibePaths, capability: AdapterCapability, decision: Any) -> tuple[str, str] | None:
    if not capability.entrypoint.get("command"):
        return "blocked_missing_script", f"{capability.id} is missing entrypoint.command"
    if not capability.dryrun.get("command"):
        return "blocked_missing_script", f"{capability.id} is missing dryrun.command"
    if not (capability.metrics_schema.required or capability.metrics_schema.types):
        return "blocked_missing_metrics_schema", f"{capability.id} is missing metrics schema"
    contract = read_json(paths.vibe / "contract_tests" / f"{capability.id}.json", {})
    if contract.get("status") != "passed" or capability.activation.get("contract_status") != "passed":
        return "blocked_contract_test_failed", f"{capability.id} has not passed contract tests"
    decision_type = getattr(decision, "decision_type", "")
    if decision_type == "launch_gpu_gate" and not capability.resources.automatic_submission_allowed:
        return "blocked_resource_policy", f"{capability.id} resource policy does not allow automatic submission"
    if decision_type == "promote_to_baseline_compare" and not getattr(decision, "baseline_comparison_target", ""):
        return "blocked_missing_resource_plan", "baseline comparison requires baseline_comparison_target"
    return None


def task_from_capability(manifest: Any, capability: AdapterCapability, decision: Any) -> dict[str, Any]:
    expected_output = capability.outputs.get("expected_output_path") or (capability.artifact_rules.expected_outputs[0] if capability.artifact_rules.expected_outputs else "")
    metrics_file = capability.outputs.get("metrics_file_path") or expected_output
    metadata = {
        "adapter_revision": manifest.adapter_revision,
        "capability_id": capability.id,
        "capability_version": capability.version,
        "command_template_hash": capability.activation.get("command_template_hash") or hash_dict(capability.entrypoint),
        "metrics_schema_version": capability.metrics_schema.version,
        "metrics_schema_hash": capability.activation.get("metrics_schema_hash") or hash_dict(capability.metrics_schema.model_dump()),
        "artifact_rule_version": capability.artifact_rules.version,
        "artifact_rule_hash": capability.activation.get("artifact_rule_hash") or hash_dict(capability.artifact_rules.model_dump()),
        "contract_test_result_id": capability.activation.get("contract_test_result_id", ""),
        "planner_selection_rationale": f"selected active capability {capability.id} for decision {getattr(decision, 'decision_type', '')}",
    }
    return {
        "key": capability.id,
        "direction_id": getattr(decision, "selected_direction", "") or capability.id,
        "hypothesis": capability.description or getattr(decision, "required_action", "") or capability.id,
        "expected_learning": capability.description or capability.id,
        "dryrun_command": capability.dryrun.get("command", ""),
        "entrypoint_command": capability.entrypoint.get("command", ""),
        "expected_output_path": expected_output,
        "metrics_file_path": metrics_file,
        "metrics_schema": metrics_schema_for_plan(capability),
        "resources": capability.resources.default,
        "trust_rules": {"checks": capability.trust_checks, "require_metrics_schema": True, "allow_manual_metric": False},
        "baseline_comparison_target": getattr(decision, "baseline_comparison_target", ""),
        "adapter_metadata": metadata,
    }


def metrics_schema_for_plan(capability: AdapterCapability) -> dict[str, Any]:
    if capability.metrics_schema.types:
        return capability.metrics_schema.types
    primary = capability.metrics_schema.primary_metric or "primary"
    return {primary: "number"}


def is_placeholder_command(command: str) -> bool:
    normalized = " ".join(command.lower().strip().split())
    if not normalized:
        return True
    if normalized in {"true", "echo ok", "python -c 'print(\"vibe run placeholder\")'", "python -c 'print(\"vibe dryrun placeholder\")'"}:
        return True
    return any(token in normalized for token in PLACEHOLDER_TOKENS)


def validate_compiled_plan(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    runs = plan.get("runs", {})
    if not isinstance(runs, dict) or not runs:
        return ["resource plan has no runs"]
    for key, spec in runs.items():
        dryrun = spec.get("dryrun", {}).get("command", "")
        entrypoint = spec.get("entrypoint", {}).get("command", "")
        evaluation = spec.get("evaluation", {})
        if is_placeholder_command(dryrun):
            errors.append(f"{key}: dryrun.command is missing or placeholder")
        if is_placeholder_command(entrypoint):
            errors.append(f"{key}: entrypoint.command is missing or placeholder")
        if not evaluation.get("metrics_file_path"):
            errors.append(f"{key}: metrics_file_path is required")
        if not evaluation.get("metrics_schema"):
            errors.append(f"{key}: metrics_schema is required")
        if not spec.get("outputs", {}).get("expected_output_path"):
            errors.append(f"{key}: expected_output_path is required")
        for resource in ["gpu", "cpus", "mem_gb", "time"]:
            if resource not in spec.get("resources", {}):
                errors.append(f"{key}: resources.{resource} is required")
    return errors
