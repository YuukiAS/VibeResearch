"""Executor Session runtime for compiled execution manifests."""

from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any

from .compiler import validate_execution_manifest
from .io import append_jsonl, read_json, utc_now, write_json, write_text
from .mve import validate_mve_completion
from .paths import VibePaths


EXECUTOR_DIR = ".vibe/executor"
RESULT_MANIFEST = "result_manifest.json"
RESULT_REPORT = "result_report.md"
ARTIFACT_INVENTORY = "artifact_inventory.json"
EXECUTION_LOG = "execution_log.jsonl"
BLOCKER_REPORT = "blocker_report.md"
EVIDENCE_ARTIFACT_TERMS = {
    "prediction",
    "pred",
    "qc",
    "mask",
    "softmax",
    "route",
    "metric",
    "metrics",
    "failure",
    "table",
    "audit",
    "evidence",
    "eval",
}
WEAK_ARTIFACT_TERMS = {
    "readme",
    "summary",
    "repo_clone",
    "clone",
    "import_success",
    "import",
    "cache",
    "metadata",
    "smoke",
    "status",
}
IMMUTABLE_DECISION_FIELDS = {
    "failure_anchor",
    "hypothesis",
    "mechanism",
    "minimum_experiment",
    "expected_belief_update",
    "promotion_criteria",
    "next_promotion_rule",
}


def load_execution_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"execution manifest not found: {path}")
    data = read_json(path, {})
    return data if isinstance(data, dict) else {}


def manifest_digest(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_scientific_boundary(manifest: dict[str, Any], proposed_updates: dict[str, Any] | None = None) -> list[str]:
    """Reject Executor attempts to rewrite reviewed scientific decisions."""

    issues: list[str] = []
    updates = proposed_updates or {}
    contract = manifest.get("mve_contract", {}) if isinstance(manifest.get("mve_contract"), dict) else {}
    protected_values = {
        "mechanism": manifest.get("mechanism", ""),
        "minimum_experiment": manifest.get("minimum_experiment", ""),
        "expected_belief_update": contract.get("success_condition", ""),
        "promotion_criteria": contract.get("next_promotion_rule", ""),
        "next_promotion_rule": contract.get("next_promotion_rule", ""),
    }
    for field in IMMUTABLE_DECISION_FIELDS:
        if field not in updates:
            continue
        original = protected_values.get(field)
        if updates[field] != original:
            issues.append(f"Executor cannot modify scientific decision field: {field}")
    return issues


def validate_executor_manifest(manifest: dict[str, Any]) -> list[str]:
    issues = validate_execution_manifest(manifest)
    resource = manifest.get("resource_plan", {}) if isinstance(manifest.get("resource_plan"), dict) else {}
    if resource.get("backend") == "slurm" and resource.get("approval_required"):
        issues.append("Slurm execution requires a separate approved operator action")
    command = manifest.get("commands", {}).get("local") if isinstance(manifest.get("commands"), dict) else None
    if not command:
        issues.append("commands.local is required for Executor run")
    issues.extend(validate_scientific_boundary(manifest))
    return issues


def validate_boundary_guard(paths: VibePaths, manifest: dict[str, Any], *, reviewed_path: Path | None = None) -> list[str]:
    issues: list[str] = []
    issues.extend(validate_review_approval_consistency(paths, manifest, reviewed_path=reviewed_path))
    issues.extend(validate_artifact_quality(manifest))
    issues.extend(validate_safety_red_lines(manifest))
    issues.extend(validate_stop_fallback_contract(manifest))
    return issues


def validate_review_approval_consistency(paths: VibePaths, manifest: dict[str, Any], *, reviewed_path: Path | None = None) -> list[str]:
    issues: list[str] = []
    reviewed_manifest_path = reviewed_path or (paths.kernel / "reviewed_plan_manifest.json")
    if not reviewed_manifest_path.exists():
        return [f"reviewed_plan_manifest is required: {reviewed_manifest_path}"]
    reviewed = read_json(reviewed_manifest_path, {})
    review = reviewed.get("review", {}) if isinstance(reviewed.get("review"), dict) else {}
    draft = reviewed.get("draft_plan", {}) if isinstance(reviewed.get("draft_plan"), dict) else {}
    body = draft.get("plan", {}) if isinstance(draft.get("plan"), dict) else {}
    if review.get("verdict") != "ACCEPT" or not review.get("allow_compiler"):
        issues.append("reviewed plan must have ACCEPT verdict and allow_compiler=true")
    if manifest.get("accepted_plan_id") != draft.get("created_at"):
        issues.append("compiler manifest accepted_plan_id does not match reviewed draft")
    if manifest.get("review_approval_id") != review.get("created_at"):
        issues.append("compiler manifest review_approval_id does not match reviewed approval")
    if manifest.get("revision_history", []) != reviewed.get("revision_history", []):
        issues.append("compiler manifest revision_history does not match reviewed manifest")
    expected_artifacts = manifest.get("expected_artifacts", [])
    expected_artifact = expected_artifacts[0] if isinstance(expected_artifacts, list) and expected_artifacts else ""
    field_pairs = {
        "mechanism": (manifest.get("mechanism", ""), body.get("mechanism", "")),
        "minimum_experiment": (manifest.get("minimum_experiment", ""), body.get("minimum_experiment", "")),
        "expected_artifact": (expected_artifact, body.get("expected_artifact", "")),
        "stop_condition": ((manifest.get("stop_conditions") or [""])[0], body.get("stop_condition", "")),
    }
    for field, (compiled, reviewed_value) in field_pairs.items():
        if compiled != reviewed_value:
            issues.append(f"compiler manifest {field} does not match reviewed plan")
    return issues


def validate_artifact_quality(manifest: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    artifacts = manifest.get("expected_artifacts", [])
    if not artifacts:
        return ["expected_artifacts are required"]
    for artifact in artifacts:
        path = str(artifact).strip().lower()
        compact = path.replace("-", "_")
        if not path:
            issues.append("expected artifact path is empty")
            continue
        if any(term in compact for term in WEAK_ARTIFACT_TERMS):
            issues.append(f"expected artifact is not evidence-grade: {artifact}")
            continue
        if not any(term in compact for term in EVIDENCE_ARTIFACT_TERMS):
            issues.append(f"expected artifact lacks evidence-grade signal: {artifact}")
    return issues


def validate_safety_red_lines(manifest: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    safety = manifest.get("safety_checks", {}) if isinstance(manifest.get("safety_checks"), dict) else {}
    resource = manifest.get("resource_plan", {}) if isinstance(manifest.get("resource_plan"), dict) else {}
    command_text = " ".join(str(value) for value in manifest.get("commands", {}).values()) if isinstance(manifest.get("commands"), dict) else ""
    input_text = " ".join(str(item) for item in manifest.get("input_assets", []))
    lowered = f"{command_text} {input_text}".lower()
    if safety.get("data_permission") in {"missing", "denied", "unknown"} or safety.get("data_permissions_approved") is False:
        issues.append("data permission is not approved")
    if safety.get("required_human_approval") and not safety.get("human_approved"):
        issues.append("required human approval is missing")
    if safety.get("upload_prohibited") and any(term in lowered for term in ("upload", "dx upload", "aws s3 cp", "scp ", "rsync ")):
        issues.append("upload is prohibited by safety policy")
    if safety.get("delete_prohibited") and any(term in lowered for term in ("rm -rf", "rm ", "unlink", "shutil.rmtree")):
        issues.append("delete is prohibited by safety policy")
    if safety.get("external_data_prohibited") and any(term in lowered for term in ("http://", "https://", "s3://", "gs://", "dx://", "wget ", "curl ")):
        issues.append("external data use is prohibited by safety policy")
    max_gpu_hours = resource.get("max_gpu_hours")
    requested_gpu_hours = resource.get("gpu_hours")
    if max_gpu_hours is not None and requested_gpu_hours is not None and float(requested_gpu_hours) > float(max_gpu_hours):
        issues.append("resource plan exceeds gpu hour cap")
    if resource.get("backend") == "slurm" and resource.get("budget_approved") is False:
        issues.append("Slurm budget is not approved")
    return issues


def validate_stop_fallback_contract(manifest: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if not manifest.get("stop_conditions") or not manifest["stop_conditions"][0]:
        issues.append("stop condition is required")
    if not manifest.get("fallbacks") or not manifest["fallbacks"][0].get("command"):
        issues.append("fallback command is required")
    if not manifest.get("failure_report_path"):
        issues.append("failure_report_path is required")
    return issues


def artifact_records(root: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    inventory = manifest.get("artifact_inventory", [])
    expected = {str(item) for item in manifest.get("expected_artifacts", [])}
    if not isinstance(inventory, list):
        inventory = []
    known_paths = set()
    for item in inventory:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", ""))
        if not path:
            continue
        known_paths.add(path)
        artifact_path = root / path
        records.append(
            {
                "path": path,
                "required": bool(item.get("required", path in expected)),
                "reader": item.get("reader", ""),
                "exists": artifact_path.exists(),
                "size_bytes": artifact_path.stat().st_size if artifact_path.exists() else 0,
            }
        )
    for path in sorted(expected - known_paths):
        artifact_path = root / path
        records.append(
            {
                "path": path,
                "required": True,
                "reader": "",
                "exists": artifact_path.exists(),
                "size_bytes": artifact_path.stat().st_size if artifact_path.exists() else 0,
            }
        )
    return records


def executor_env(root: Path) -> dict[str, str]:
    return {
        "cwd": str(root),
        "python": platform.python_version(),
        "python_executable": sys.executable,
        "platform": platform.platform(),
    }


def run_execution_manifest(
    paths: VibePaths,
    manifest: dict[str, Any],
    *,
    manifest_path: Path | None = None,
    timeout_seconds: int = 600,
    dry_run: bool = False,
    proposed_updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issues = validate_executor_manifest(manifest)
    issues.extend(validate_boundary_guard(paths, manifest))
    issues.extend(validate_scientific_boundary(manifest, proposed_updates))
    if issues:
        return write_blocker_result(paths, manifest, issues, manifest_path=manifest_path, status="blocked_invalid_manifest")

    command = str(manifest.get("commands", {}).get("local", ""))
    started_at = utc_now()
    completed = subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
    if not dry_run:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=paths.root,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    ended_at = utc_now()
    log_record = {
        "event": "executor_command",
        "started_at": started_at,
        "ended_at": ended_at,
        "command": command,
        "dry_run": dry_run,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "slurm_job_id": "",
        "env": executor_env(paths.root),
        "input_assets": manifest.get("input_assets", []),
        "expected_artifacts": manifest.get("expected_artifacts", []),
        "manifest_digest": manifest_digest(manifest_path),
    }
    append_jsonl(paths.root / EXECUTOR_DIR / EXECUTION_LOG, log_record)

    if dry_run:
        return write_blocker_result(paths, manifest, ["dry run did not execute the MVE command"], manifest_path=manifest_path, status="blocked_dry_run")
    if completed.returncode != 0:
        return write_blocker_result(paths, manifest, [f"command failed with exit code {completed.returncode}"], manifest_path=manifest_path, status="blocked_command_failed")

    records = artifact_records(paths.root, manifest)
    write_json(paths.root / EXECUTOR_DIR / ARTIFACT_INVENTORY, records)
    missing = [record["path"] for record in records if record.get("required") and not record.get("exists")]
    mve_issues = validate_mve_completion(paths.root, manifest)
    if missing or mve_issues:
        blocker_issues = [f"expected artifact missing: {path}" for path in missing]
        blocker_issues.extend(issue for issue in mve_issues if issue not in blocker_issues)
        return write_blocker_result(paths, manifest, blocker_issues, manifest_path=manifest_path, status="blocked_missing_expected_artifact")

    result = build_result_manifest(paths, manifest, records, manifest_path=manifest_path, status="completed", issues=[])
    write_json(paths.root / EXECUTOR_DIR / RESULT_MANIFEST, result)
    write_result_report(paths.root / EXECUTOR_DIR / RESULT_REPORT, result)
    return result


def build_result_manifest(
    paths: VibePaths,
    manifest: dict[str, Any],
    artifact_inventory: list[dict[str, Any]],
    *,
    manifest_path: Path | None,
    status: str,
    issues: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "session_role": "executor",
        "status": status,
        "source_manifest": str(manifest_path) if manifest_path else "",
        "manifest_digest": manifest_digest(manifest_path),
        "accepted_plan_id": manifest.get("accepted_plan_id", ""),
        "review_approval_id": manifest.get("review_approval_id", ""),
        "mechanism": manifest.get("mechanism", ""),
        "minimum_experiment": manifest.get("minimum_experiment", ""),
        "mve_contract": manifest.get("mve_contract", {}),
        "input_assets": manifest.get("input_assets", []),
        "expected_artifacts": manifest.get("expected_artifacts", []),
        "artifact_inventory_path": f"{EXECUTOR_DIR}/{ARTIFACT_INVENTORY}",
        "execution_log_path": f"{EXECUTOR_DIR}/{EXECUTION_LOG}",
        "result_report_path": f"{EXECUTOR_DIR}/{RESULT_REPORT}",
        "blocker_report_path": f"{EXECUTOR_DIR}/{BLOCKER_REPORT}" if status.startswith("blocked") else "",
        "artifact_inventory": artifact_inventory,
        "provenance": {
            "commands": manifest.get("commands", {}),
            "resource_plan": manifest.get("resource_plan", {}),
            "env": executor_env(paths.root),
            "slurm_job_id": "",
            "stdout_stderr": f"{EXECUTOR_DIR}/{EXECUTION_LOG}",
        },
        "issues": issues,
        "scientific_boundary": {"executor_may_modify_scientific_decisions": False},
    }


def write_blocker_result(
    paths: VibePaths,
    manifest: dict[str, Any],
    issues: list[str],
    *,
    manifest_path: Path | None,
    status: str,
) -> dict[str, Any]:
    records = artifact_records(paths.root, manifest)
    write_json(paths.root / EXECUTOR_DIR / ARTIFACT_INVENTORY, records)
    result = build_result_manifest(paths, manifest, records, manifest_path=manifest_path, status=status, issues=issues)
    write_json(paths.root / EXECUTOR_DIR / RESULT_MANIFEST, result)
    write_blocker_report(paths.root / EXECUTOR_DIR / BLOCKER_REPORT, result)
    write_result_report(paths.root / EXECUTOR_DIR / RESULT_REPORT, result)
    return result


def write_blocker_report(path: Path, result: dict[str, Any]) -> None:
    issue_lines = "\n".join(f"- {issue}" for issue in result.get("issues", [])) or "- unspecified blocker"
    write_text(
        path,
        "\n".join(
            [
                "# Executor Blocker Report",
                "",
                f"Status: {result.get('status', '')}",
                "",
                "## Blockers",
                issue_lines,
                "",
                "## Boundary",
                "Executor did not change the reviewed failure anchor, hypothesis, mechanism, MVE, or promotion rule.",
                "",
            ]
        ),
    )


def write_result_report(path: Path, result: dict[str, Any]) -> None:
    artifacts = result.get("artifact_inventory", [])
    artifact_lines = "\n".join(
        f"- {item.get('path')}: {'present' if item.get('exists') else 'missing'} ({item.get('size_bytes', 0)} bytes)" for item in artifacts
    )
    issue_lines = "\n".join(f"- {issue}" for issue in result.get("issues", [])) or "- none"
    write_text(
        path,
        "\n".join(
            [
                "# Executor Result Report",
                "",
                "## Result Summary",
                f"- Status: {result.get('status', '')}",
                f"- Mechanism: {result.get('mechanism', '')}",
                f"- Minimum experiment: {result.get('minimum_experiment', '')}",
                "",
                "## Artifacts",
                artifact_lines or "- none",
                "",
                "## Provenance",
                f"- Source manifest: {result.get('source_manifest', '')}",
                f"- Manifest digest: {result.get('manifest_digest', '')}",
                f"- Execution log: {result.get('execution_log_path', '')}",
                f"- Slurm job id: {result.get('provenance', {}).get('slurm_job_id', '')}",
                "",
                "## Issues",
                issue_lines,
                "",
            ]
        ),
    )


def validate_result_manifest(paths: VibePaths, result: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if result.get("session_role") != "executor":
        issues.append("session_role must be executor")
    if not result.get("source_manifest"):
        issues.append("source_manifest is required")
    if not result.get("execution_log_path"):
        issues.append("execution_log_path is required")
    if not result.get("artifact_inventory_path"):
        issues.append("artifact_inventory_path is required")
    report_path = paths.root / str(result.get("result_report_path", ""))
    if not report_path.exists():
        issues.append("result_report is required")
    else:
        text = report_path.read_text()
        for heading in ("## Result Summary", "## Artifacts", "## Provenance"):
            if heading not in text:
                issues.append(f"result_report missing {heading}")
    records = result.get("artifact_inventory", [])
    missing = [record.get("path", "") for record in records if isinstance(record, dict) and record.get("required") and not record.get("exists")]
    if result.get("status") == "completed" and missing:
        issues.append("completed result cannot have missing required artifacts")
    if str(result.get("status", "")).startswith("blocked"):
        blocker_path = paths.root / str(result.get("blocker_report_path", ""))
        if not blocker_path.exists():
            issues.append("blocked result requires blocker_report")
    return issues
