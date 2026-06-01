"""Compiler Session translation from reviewed plans to execution manifests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import read_json, slugify, utc_now, write_json, write_text
from .paths import VibePaths


def compile_reviewed_plan(paths: VibePaths, reviewed: dict[str, Any]) -> dict[str, Any]:
    review = reviewed.get("review", {}) if isinstance(reviewed.get("review"), dict) else {}
    draft = reviewed.get("draft_plan", {}) if isinstance(reviewed.get("draft_plan"), dict) else {}
    if review.get("verdict") != "ACCEPT" or not review.get("allow_compiler"):
        raise ValueError("review approval is missing or not ACCEPT")
    body = draft.get("plan", {}) if isinstance(draft.get("plan"), dict) else {}
    expected_artifact = str(body.get("expected_artifact", "")).strip()
    metric_reader = metric_reader_for(expected_artifact)
    if not concrete_artifact_path(expected_artifact):
        raise ValueError("expected artifact must be a concrete repo-local path")
    if not metric_reader:
        raise ValueError("metric reader cannot be inferred from expected artifact")

    mechanism_slug = slugify(str(body.get("mechanism", "execution")), max_len=32)
    script_path = f".vibe/executor/scripts/{mechanism_slug}.sh"
    slurm_path = f".vibe/executor/slurm/{mechanism_slug}.sbatch"
    command = render_local_command(expected_artifact, body)
    manifest = {
        "schema_version": 1,
        "created_at": utc_now(),
        "session_role": "compiler",
        "accepted_plan_id": draft.get("created_at", ""),
        "review_approval_id": review.get("created_at", ""),
        "repo_paths": {
            "root": str(paths.root),
            "kernel": ".vibe/kernel",
            "script": script_path,
            "slurm_draft": slurm_path,
        },
        "input_assets": [".vibe/kernel/reviewed_plan_manifest.json"],
        "mechanism": body.get("mechanism", ""),
        "minimum_experiment": body.get("minimum_experiment", ""),
        "commands": {
            "local": command,
            "script": f"bash {script_path}",
        },
        "resource_plan": infer_resource_plan(str(body.get("compute_cost", ""))),
        "expected_artifacts": [expected_artifact],
        "evaluation_commands": [{"reader": metric_reader, "command": f"python -m vibe_research.cli validate-artifact execution_manifest {mechanism_slug}"}],
        "stop_conditions": [body.get("stop_condition", "")],
        "fallbacks": [{"command": f"echo {body.get('fallback', 'record blocker')!r}", "rationale": body.get("fallback", "")}],
        "artifact_inventory": [{"path": expected_artifact, "required": True, "reader": metric_reader}],
        "safety_checks": {
            "review_verdict": review.get("verdict"),
            "allow_compiler": review.get("allow_compiler"),
            "reviewer_criteria": review.get("criteria", []),
            "blocking_risks": review.get("blocking_risks", []),
            "required_changes": review.get("required_changes", []),
        },
        "review_trace": review.get("trace", {}),
        "revision_history": reviewed.get("revision_history", []),
    }
    issues = validate_execution_manifest(manifest)
    if issues:
        raise ValueError("; ".join(issues))
    return manifest


def concrete_artifact_path(path: str) -> bool:
    return bool(path and path.startswith(".vibe/") and not path.endswith("/") and " " not in path)


def metric_reader_for(path: str) -> str:
    lowered = path.lower()
    if lowered.endswith(".json"):
        return "json"
    if lowered.endswith(".csv"):
        return "csv"
    if lowered.endswith(".md"):
        return "markdown"
    return ""


def infer_resource_plan(compute_cost: str) -> dict[str, Any]:
    lowered = compute_cost.lower()
    if "gpu" in lowered or "slurm" in lowered:
        return {"backend": "slurm", "gpu": 1, "approval_required": True, "source": compute_cost}
    return {"backend": "local", "gpu": 0, "approval_required": False, "source": compute_cost}


def render_local_command(expected_artifact: str, body: dict[str, Any]) -> str:
    payload = {
        "status": "pending_execution",
        "mechanism": body.get("mechanism", ""),
        "minimum_experiment": body.get("minimum_experiment", ""),
        "expected_belief_update": body.get("expected_belief_update", ""),
    }
    return (
        "python -c "
        + repr(
            "import json,pathlib; "
            f"p=pathlib.Path({expected_artifact!r}); "
            "p.parent.mkdir(parents=True, exist_ok=True); "
            f"p.write_text(json.dumps({payload!r}, sort_keys=True)+'\\n')"
        )
    )


def write_execution_package(paths: VibePaths, manifest: dict[str, Any], output: str = "execution_manifest.json") -> dict[str, Path]:
    manifest_path = paths.kernel / output
    script_path = paths.root / manifest["repo_paths"]["script"]
    slurm_path = paths.root / manifest["repo_paths"]["slurm_draft"]
    write_json(manifest_path, manifest)
    write_text(script_path, "#!/usr/bin/env bash\nset -euo pipefail\n" + manifest["commands"]["local"] + "\n")
    write_text(slurm_path, "#!/usr/bin/env bash\n# Slurm draft; review resources before submission.\n" + manifest["commands"]["script"] + "\n")
    return {"manifest": manifest_path, "script": script_path, "slurm_draft": slurm_path}


def validate_execution_manifest(manifest: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if manifest.get("session_role") != "compiler":
        issues.append("session_role must be compiler")
    if not manifest.get("accepted_plan_id"):
        issues.append("accepted_plan_id is required")
    if not manifest.get("review_approval_id"):
        issues.append("review_approval_id is required")
    if not manifest.get("expected_artifacts"):
        issues.append("expected_artifacts are required")
    for artifact in manifest.get("expected_artifacts", []):
        if not concrete_artifact_path(str(artifact)):
            issues.append(f"artifact path is not concrete: {artifact}")
    if not manifest.get("evaluation_commands"):
        issues.append("evaluation_commands are required")
    if not manifest.get("stop_conditions") or not manifest["stop_conditions"][0]:
        issues.append("stop condition is required")
    if not manifest.get("fallbacks") or not manifest["fallbacks"][0].get("command"):
        issues.append("fallback command is required")
    safety = manifest.get("safety_checks", {})
    if safety.get("review_verdict") != "ACCEPT" or not safety.get("allow_compiler"):
        issues.append("accepted review approval must be preserved")
    return issues


def load_reviewed_plan(path: Path) -> dict[str, Any]:
    return read_json(path, {})
