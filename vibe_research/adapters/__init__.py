"""Project adapter interface and built-in generic adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import load_config
from ..io import read_yaml
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
        task = (self.adapter_config or {}).get("task", {})
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
    kind = adapter_config.get("kind", "noop")
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
                "depends_on": list(task.get("depends_on", [])),
                "cancel_if_failed": list(task.get("cancel_if_failed", [])),
            }
        },
        "cancel_rules": list(task.get("cancel_rules", [])),
    }


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
