"""Long-run reliability and soak diagnostics."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .adapter_schema import load_adapter_manifest
from .io import append_jsonl, ensure_dir, read_json, read_jsonl, read_yaml, utc_now, write_json
from .paths import VibePaths
from .research_manager import research_paths


ACTIVE_RUN_STATUSES = {"pending", "submitted", "running", "active"}
BLOCKED_STATUSES = {"blocked", "failed", "stale"}
SAFE_COMMAND_PREFIXES = (
    "vibe status",
    "vibe monitor",
    "vibe collect",
    "vibe reflect",
    "vibe revise-plan",
    "vibe budget status",
    "vibe memo daily",
    "vibe adapter doctor",
    "vibe dashboard export-research",
    "vibe reliability checkpoint",
    "vibe reliability report",
)


def reliability_dir(paths: VibePaths):
    return ensure_dir(paths.research / "reliability")


def reliability_paths(paths: VibePaths) -> dict[str, Path]:
    base = reliability_dir(paths)
    return {
        "latest_report": base / "latest_report.json",
        "doctor": base / "doctor.json",
        "checkpoints": base / "checkpoints.jsonl",
        "latest_checkpoint": base / "latest_checkpoint.json",
        "comparison": base / "checkpoint_comparison.json",
    }


def reliability_report(paths: VibePaths, *, stale_hours: float = 24.0, memo_fresh_hours: float = 24.0) -> dict[str, Any]:
    state = read_json(paths.state / "state.json", {})
    checks = [
        check_active_run_consistency(paths, state, stale_hours=stale_hours),
        check_stale_blockers(paths, stale_hours=stale_hours),
        check_budget_drift(paths),
        check_memo_freshness(paths, memo_fresh_hours=memo_fresh_hours),
        check_adapter_evolution(paths),
        check_dashboard_exports(paths),
        check_dual_track_health(paths),
    ]
    issues = [issue for check in checks for issue in check.get("issues", [])]
    warnings = [warning for check in checks for warning in check.get("warnings", [])]
    report = {
        "created_at": utc_now(),
        "status": "blocked" if issues else "warning" if warnings else "ok",
        "checks": {check["name"]: check for check in checks},
        "issues": issues,
        "warnings": warnings,
        "safe_recommendations": safe_recommendations(issues, warnings),
    }
    write_json(reliability_paths(paths)["latest_report"], report)
    return report


def reliability_checkpoint(paths: VibePaths, *, label: str = "") -> dict[str, Any]:
    report = reliability_report(paths)
    state = read_json(paths.state / "state.json", {})
    checkpoint = {
        "checkpoint_id": checkpoint_id(paths),
        "created_at": utc_now(),
        "label": label,
        "status": report.get("status", ""),
        "issue_count": len(report.get("issues", [])),
        "warning_count": len(report.get("warnings", [])),
        "active_runs": sorted(active_run_ids(state)),
        "blocked_runs": sorted(blocked_run_ids(state)),
        "budget": report.get("checks", {}).get("budget_drift", {}).get("summary", {}),
        "memo": report.get("checks", {}).get("memo_freshness", {}).get("summary", {}),
        "adapter": report.get("checks", {}).get("adapter_evolution", {}).get("summary", {}),
        "dashboard": report.get("checks", {}).get("dashboard_exports", {}).get("summary", {}),
    }
    files = reliability_paths(paths)
    append_jsonl(files["checkpoints"], checkpoint)
    write_json(files["latest_checkpoint"], checkpoint)
    return checkpoint


def compare_checkpoints(paths: VibePaths, *, older_id: str = "", newer_id: str = "") -> dict[str, Any]:
    checkpoints = read_jsonl(reliability_paths(paths)["checkpoints"])
    if not checkpoints:
        result = {"created_at": utc_now(), "status": "empty", "deltas": {}, "older": {}, "newer": {}}
        write_json(reliability_paths(paths)["comparison"], result)
        return result
    older = find_checkpoint(checkpoints, older_id) or (checkpoints[-2] if len(checkpoints) >= 2 else checkpoints[-1])
    newer = find_checkpoint(checkpoints, newer_id) or checkpoints[-1]
    deltas = {
        "issue_count": int(newer.get("issue_count", 0)) - int(older.get("issue_count", 0)),
        "warning_count": int(newer.get("warning_count", 0)) - int(older.get("warning_count", 0)),
        "active_runs_added": sorted(set(newer.get("active_runs", [])) - set(older.get("active_runs", []))),
        "active_runs_removed": sorted(set(older.get("active_runs", [])) - set(newer.get("active_runs", []))),
        "blocked_runs_added": sorted(set(newer.get("blocked_runs", [])) - set(older.get("blocked_runs", []))),
        "blocked_runs_removed": sorted(set(older.get("blocked_runs", [])) - set(newer.get("blocked_runs", []))),
    }
    result = {"created_at": utc_now(), "status": "compared", "older": older, "newer": newer, "deltas": deltas}
    write_json(reliability_paths(paths)["comparison"], result)
    return result


def reliability_doctor(paths: VibePaths, *, stale_hours: float = 24.0, memo_fresh_hours: float = 24.0) -> dict[str, Any]:
    report = reliability_report(paths, stale_hours=stale_hours, memo_fresh_hours=memo_fresh_hours)
    result = {
        "created_at": utc_now(),
        "ok": report.get("status") == "ok",
        "status": report.get("status"),
        "issues": report.get("issues", []),
        "warnings": report.get("warnings", []),
        "safe_recommendations": report.get("safe_recommendations", []),
        "no_live_mutation": True,
    }
    write_json(reliability_paths(paths)["doctor"], result)
    return result


def check_active_run_consistency(paths: VibePaths, state: dict[str, Any], *, stale_hours: float) -> dict[str, Any]:
    issues = []
    warnings = []
    runs = state.get("runs", {}) if isinstance(state.get("runs"), dict) else {}
    queue = read_queue(paths)
    queue_ids = {row.get("run_id", "") or row.get("id", "") for row in queue}
    for run_id, run in runs.items():
        status = run.get("status", "")
        if status not in ACTIVE_RUN_STATUSES:
            continue
        if is_stale(run, stale_hours):
            issues.append(f"{run_id}:stale_active_run")
        if queue_ids and run_id not in queue_ids and not run.get("backend_job_id") and not run.get("slurm_job_id"):
            issues.append(f"{run_id}:active_run_missing_queue_or_backend_job")
    for item in queue:
        run_id = item.get("run_id", "") or item.get("id", "")
        if item.get("status") in ACTIVE_RUN_STATUSES and run_id and run_id not in runs:
            warnings.append(f"{run_id}:queue_item_missing_state_run")
    return {"name": "active_run_consistency", "status": "blocked" if issues else "warning" if warnings else "ok", "issues": issues, "warnings": warnings, "summary": {"active_runs": sorted(active_run_ids(state)), "queue_items": len(queue)}}


def check_stale_blockers(paths: VibePaths, *, stale_hours: float) -> dict[str, Any]:
    issues = []
    warnings = []
    state = read_json(paths.state / "state.json", {})
    if state.get("blocked_reason") and age_hours_from_text(state.get("updated_at", "")) > stale_hours:
        issues.append("state:stale_blocked_reason")
    for row in read_jsonl(research_paths(paths)["questions"]):
        if row.get("status", "open") == "open" and age_hours_from_text(row.get("updated_at") or row.get("created_at", "")) > stale_hours:
            warnings.append(f"{row.get('question_id', 'question')}:stale_open_question")
    for row in read_jsonl(research_paths(paths)["decisions"]):
        if row.get("final_outcome") == "blocked" and age_hours_from_text(row.get("created_at", "")) > stale_hours:
            warnings.append(f"{row.get('decision_id', 'decision')}:stale_block_decision")
    return {"name": "stale_blockers", "status": "blocked" if issues else "warning" if warnings else "ok", "issues": issues, "warnings": warnings, "summary": {"blocked_reason": state.get("blocked_reason", "")}}


def check_budget_drift(paths: VibePaths) -> dict[str, Any]:
    issues = []
    warnings = []
    policy = read_yaml(paths.policies / "budget.yaml", {}) or {}
    ledger = read_jsonl(research_paths(paths)["budget"])
    total_gpu = sum(float(row.get("gpu_hours", row.get("amount", 0.0)) or 0.0) for row in ledger if row.get("status", "reserved") in {"reserved", "spent", "committed"})
    total_cap = float(policy.get("total_gpu_hour_cap", 0.0) or 0.0)
    daily_cap = float(policy.get("daily_gpu_hour_cap", 0.0) or 0.0)
    if total_cap and total_gpu > total_cap:
        issues.append("budget:total_gpu_hour_cap_exceeded")
    elif total_cap and total_gpu > total_cap * 0.8:
        warnings.append("budget:total_gpu_hour_cap_near_limit")
    if daily_cap and total_gpu > daily_cap:
        warnings.append("budget:daily_gpu_hour_cap_may_need_reconciliation")
    return {"name": "budget_drift", "status": "blocked" if issues else "warning" if warnings else "ok", "issues": issues, "warnings": warnings, "summary": {"reserved_or_spent_gpu_hours": total_gpu, "total_gpu_hour_cap": total_cap, "daily_gpu_hour_cap": daily_cap}}


def check_memo_freshness(paths: VibePaths, *, memo_fresh_hours: float) -> dict[str, Any]:
    issues = []
    warnings = []
    memo_files = sorted(paths.memos.glob("*.md")) if paths.memos.exists() else []
    if not memo_files:
        warnings.append("memo:no_recent_memo")
        latest = ""
        age = None
    else:
        latest_file = memo_files[-1]
        latest = str(latest_file.relative_to(paths.root))
        age = (datetime.now(timezone.utc) - datetime.fromtimestamp(latest_file.stat().st_mtime, tz=timezone.utc)).total_seconds() / 3600
        if age > memo_fresh_hours:
            warnings.append("memo:stale_memo")
    return {"name": "memo_freshness", "status": "warning" if warnings else "ok", "issues": issues, "warnings": warnings, "summary": {"latest_memo": latest, "age_hours": age}}


def check_adapter_evolution(paths: VibePaths) -> dict[str, Any]:
    issues = []
    warnings = []
    try:
        manifest = load_adapter_manifest(paths)
    except Exception as exc:
        return {"name": "adapter_evolution", "status": "blocked", "issues": [f"adapter:manifest_unreadable:{exc}"], "warnings": [], "summary": {}}
    active = [cap for cap in manifest.capabilities if cap.status == "active"]
    if active and not (paths.vibe / "adapter_lint.json").exists():
        warnings.append("adapter:active_capabilities_without_recent_lint_report")
    for cap in active:
        if not cap.contract_tests:
            issues.append(f"{cap.id}:missing_contract_tests")
        if not cap.trust_checks:
            issues.append(f"{cap.id}:missing_trust_checks")
    return {"name": "adapter_evolution", "status": "blocked" if issues else "warning" if warnings else "ok", "issues": issues, "warnings": warnings, "summary": {"adapter_revision": str(manifest.adapter_revision), "active_capabilities": [cap.id for cap in active], "maturity_level": manifest.maturity_level}}


def check_dashboard_exports(paths: VibePaths) -> dict[str, Any]:
    warnings = []
    expected = [paths.dashboard / "research.json", paths.dashboard / "status.md"]
    missing = [str(path.relative_to(paths.root)) for path in expected if not path.exists()]
    if missing:
        warnings.append("dashboard:missing_exports")
    return {"name": "dashboard_exports", "status": "warning" if warnings else "ok", "issues": [], "warnings": warnings, "summary": {"missing": missing}}


def check_dual_track_health(paths: VibePaths) -> dict[str, Any]:
    warnings = []
    base = paths.research / "dual_track"
    rows = read_jsonl(base / "track_experiments.jsonl")
    internal = [row for row in rows if row.get("track") in {"internal", "hybrid"}]
    if internal and not any(row.get("external_baseline_asset_id") for row in internal):
        warnings.append("dual_track:internal_records_missing_external_baseline")
    if internal and not any(row.get("metrics_comparable") for row in internal):
        warnings.append("dual_track:no_comparable_internal_metrics")
    return {"name": "dual_track_health", "status": "warning" if warnings else "ok", "issues": [], "warnings": warnings, "summary": {"track_records": len(rows), "internal_or_hybrid_records": len(internal)}}


def safe_recommendations(issues: list[str], warnings: list[str]) -> list[str]:
    recs = []
    signals = issues + warnings
    if any("active_run" in item or "queue" in item for item in signals):
        recs.append("vibe monitor --target <repo> --once")
        recs.append("vibe collect <run_id> --target <repo>")
    if any("blocked" in item or "question" in item for item in signals):
        recs.append("vibe research questions --target <repo>")
    if any("budget" in item for item in signals):
        recs.append("vibe budget status --target <repo>")
    if any("memo" in item for item in signals):
        recs.append("vibe memo daily --target <repo>")
    if any("adapter" in item for item in signals):
        recs.append("vibe adapter doctor --target <repo>")
    if any("dashboard" in item for item in signals):
        recs.append("vibe dashboard export-research --target <repo>")
    recs.append("vibe reliability checkpoint --target <repo>")
    return [rec for rec in dedupe(recs) if is_safe_recommendation(rec)]


def read_queue(paths: VibePaths) -> list[dict[str, Any]]:
    for path in [paths.scheduler / "queue.json", paths.state / "queue.json", paths.vibe / "queue.json"]:
        data = read_json(path, [])
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and isinstance(data.get("queue"), list):
            return data["queue"]
    return []


def active_run_ids(state: dict[str, Any]) -> set[str]:
    runs = state.get("runs", {}) if isinstance(state.get("runs"), dict) else {}
    return {run_id for run_id, run in runs.items() if run.get("status") in ACTIVE_RUN_STATUSES}


def blocked_run_ids(state: dict[str, Any]) -> set[str]:
    runs = state.get("runs", {}) if isinstance(state.get("runs"), dict) else {}
    return {run_id for run_id, run in runs.items() if run.get("status") in BLOCKED_STATUSES}


def is_stale(row: dict[str, Any], stale_hours: float) -> bool:
    return age_hours_from_text(row.get("updated_at") or row.get("submitted_at") or row.get("created_at", "")) > stale_hours


def age_hours_from_text(value: str) -> float:
    if not value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).total_seconds() / 3600


def checkpoint_id(paths: VibePaths) -> str:
    existing = [row.get("checkpoint_id", "") for row in read_jsonl(reliability_paths(paths)["checkpoints"])]
    return f"soak_{len([item for item in existing if item.startswith('soak_')]) + 1:03d}"


def find_checkpoint(rows: list[dict[str, Any]], checkpoint_id_value: str) -> dict[str, Any] | None:
    if not checkpoint_id_value:
        return None
    return next((row for row in rows if row.get("checkpoint_id") == checkpoint_id_value), None)


def is_safe_recommendation(command: str) -> bool:
    lowered = command.lower()
    if any(token in lowered for token in ["sbatch", "scancel", "submit-queue", "cancel ", "rm ", "git reset"]):
        return False
    return command.startswith(SAFE_COMMAND_PREFIXES)


def dedupe(values: list[str]) -> list[str]:
    seen = set()
    out = []
    for value in values:
        if value not in seen:
            seen.add(value)
            out.append(value)
    return out
