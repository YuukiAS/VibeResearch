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
