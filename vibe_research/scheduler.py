"""Budget-aware deterministic queue and local/Slurm execution scaffolding."""

from __future__ import annotations

import shlex
import subprocess
import hashlib
import json
import platform
from pathlib import Path
from typing import Any

from .adapters import is_placeholder_command
from .backends import get_backend
from .config import load_config
from .dashboard import sync_dashboard
from .io import append_jsonl, read_json, read_jsonl, read_yaml, utc_now, write_json, write_text
from .manifest import validate_manifest
from .paths import VibePaths
from .timeline import record_event


def review_cycle(paths: VibePaths, cycle_id: str) -> None:
    review_path = paths.cycles / cycle_id / "portfolio_review.md"
    if not review_path.exists() or not review_path.read_text().strip() or "PENDING" in review_path.read_text():
        review_path.write_text("# Portfolio Review\n\nVerdict: APPROVE_WITH_RESOURCE_GUARDS\n\nGuards: cheap diagnostics first; respect scheduler budget.\n")
    verdict = parse_verdict(review_path.read_text())
    state = read_json(paths.state / "state.json", {})
    cycle = state.setdefault("cycles", {}).setdefault(cycle_id, {})
    cycle["review_verdict"] = verdict
    if verdict in {"BLOCK_PORTFOLIO", "REVISE_PORTFOLIO"}:
        cycle["status"] = "blocked"
        state["status"] = "portfolio_blocked"
        state["blocked_reason"] = f"portfolio verdict {verdict}"
        state["next_action"] = f"revise portfolio {cycle_id}"
    else:
        cycle["status"] = "reviewed"
        state["status"] = "portfolio_reviewed"
        state["blocked_reason"] = ""
        state["next_action"] = f"vibe generate-runs {cycle_id}"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "portfolio_reviewed", verdict or "unknown", cycle_id=cycle_id, status="blocked" if verdict in {"BLOCK_PORTFOLIO", "REVISE_PORTFOLIO"} else "approved")
    sync_dashboard(paths)


def review_run(paths: VibePaths, run_id: str) -> None:
    state = read_json(paths.state / "state.json", {})
    run = state.get("runs", {}).get(run_id)
    if not run:
        raise ValueError(f"Unknown run: {run_id}")
    review_path = paths.runs / run_id / "review.md"
    if not review_path.exists() or not review_path.read_text().strip() or "PENDING" in review_path.read_text():
        review_path.write_text("# Run Review\n\nVerdict: APPROVE_WITH_GUARDS\n\nGuards: dry-run must pass and metric provenance must be collected.\n")
    verdict = parse_verdict(review_path.read_text())
    run["review_verdict"] = verdict
    if verdict == "REVISE_OR_BLOCK":
        run["status"] = "blocked"
        state["next_action"] = f"revise run {run_id}"
        state["blocked_reason"] = f"run verdict {verdict}"
    else:
        run["status"] = "reviewed"
        state["next_action"] = f"vibe branch {run_id}"
        state["blocked_reason"] = ""
    state["runs"][run_id] = run
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "run_reviewed", verdict or "unknown", cycle_id=run.get("cycle_id", ""), run_id=run_id, direction_id=run.get("direction_id", ""), status="blocked" if verdict == "REVISE_OR_BLOCK" else "approved")
    sync_dashboard(paths)


def run_dryrun(paths: VibePaths, run_id: str) -> dict[str, Any]:
    state = read_json(paths.state / "state.json", {})
    run = state.get("runs", {}).get(run_id)
    if not run:
        raise ValueError(f"Unknown run: {run_id}")
    issues = validate_manifest(paths, run_id)
    errors = [issue.message for issue in issues if issue.level == "error"]
    if errors:
        raise RuntimeError("Manifest validation failed: " + "; ".join(errors))
    command = run.get("dryrun", {}).get("command") or "python -c 'print(\"dryrun\")'"
    result = subprocess.run(shlex.split(command), cwd=paths.root, text=True, capture_output=True, timeout=run.get("dryrun", {}).get("max_minutes", 5) * 60, check=False)
    dryrun_record = {
        "run_id": run_id,
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout[-4000:],
        "stderr": result.stderr[-4000:],
        "finished_at": utc_now(),
    }
    write_json(paths.runs / run_id / "dryrun.json", dryrun_record)
    run["status"] = "dryrun_passed" if result.returncode == 0 else "dryrun_failed"
    state["runs"][run_id] = run
    state["next_action"] = f"vibe queue {run_id}" if result.returncode == 0 else f"fix dryrun for {run_id}"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    event = "dryrun_passed" if result.returncode == 0 else "blocked"
    record_event(paths, event, f"Dry-run returncode={result.returncode}", cycle_id=run.get("cycle_id", ""), run_id=run_id, status=run["status"])
    sync_dashboard(paths)
    return dryrun_record


def queue_run(paths: VibePaths, run_id: str) -> None:
    state = read_json(paths.state / "state.json", {})
    run = state.get("runs", {}).get(run_id)
    if not run:
        raise ValueError(f"Unknown run: {run_id}")
    if run.get("status") != "dryrun_passed":
        raise RuntimeError(f"Run {run_id} is not ready for queue; status={run.get('status')}")
    queue = read_json(paths.scheduler / "queue.json", {"queued": []})
    if run_id not in [item["run_id"] for item in queue["queued"]]:
        queue["queued"].append({"run_id": run_id, "priority": int(run.get("priority", 100)), "queued_at": utc_now(), "status": "queued", "reason": ""})
    write_json(paths.scheduler / "queue.json", queue)
    run["status"] = "queued"
    state["runs"][run_id] = run
    state["next_action"] = "vibe submit-queue"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "run_queued", f"Queued {run_id}", cycle_id=run.get("cycle_id", ""), run_id=run_id, status="queued")
    sync_dashboard(paths)


def submit_queue(paths: VibePaths, *, dry: bool = False, backend_name: str | None = None) -> list[str]:
    state = read_json(paths.state / "state.json", {})
    queue = read_json(paths.scheduler / "queue.json", {"queued": []})
    active = read_json(paths.scheduler / "active_jobs.json", {"active": []})
    config = load_config(paths)
    budget = read_yaml(paths.scheduler / "budget.yaml", {}) or config.get("scheduler", {})
    max_parallel = int(budget.get("max_parallel_jobs", 3))
    max_gpu = int(budget.get("max_parallel_gpu_jobs", budget.get("max_gpu_jobs", 2)))
    backend = get_backend(paths, backend_name)
    submitted: list[str] = []
    remaining = []
    for item in sorted(queue.get("queued", []), key=lambda row: row.get("priority", 100)):
        run_id = item["run_id"]
        run = state.get("runs", {}).get(run_id, {})
        cycle = state.get("cycles", {}).get(run.get("cycle_id", ""), {})
        if cycle.get("status") == "blocked" or cycle.get("review_verdict") in {"BLOCK_PORTFOLIO", "REVISE_PORTFOLIO"}:
            item["status"] = "portfolio_blocked"
            item["reason"] = f"cycle {run.get('cycle_id', '')} is blocked"
            remaining.append(item)
            continue
        issues = validate_manifest(paths, run_id)
        errors = [issue.message for issue in issues if issue.level == "error"]
        if errors:
            item["status"] = "manifest_error"
            item["reason"] = "; ".join(errors[:3])
            remaining.append(item)
            continue
        if paused_direction(paths, run.get("direction_id", "")):
            item["status"] = "paused_direction"
            item["reason"] = f"direction {run.get('direction_id', '')} is paused/stopped"
            remaining.append(item)
            continue
        if dependencies_blocked(state, run):
            item["status"] = "waiting_on_dependency"
            item["reason"] = "run_after dependency is not collected/reflected/revised/merged"
            remaining.append(item)
            continue
        candidate_gpu = int((run.get("resources") or {}).get("gpu", 0) or 0)
        if len(active["active"]) >= max_parallel:
            item["status"] = "waiting_on_budget"
            item["reason"] = f"max_parallel_jobs={max_parallel}"
            remaining.append(item)
            continue
        if active_gpu_count(active["active"]) + candidate_gpu > max_gpu:
            item["status"] = "waiting_on_budget"
            item["reason"] = f"max_gpu_jobs={max_gpu}"
            remaining.append(item)
            continue
        launch = submit_run(paths, run_id, dry=dry, backend_name=backend.name)
        active["active"].append(launch)
        run["status"] = "submitted_dry" if dry else "submitted"
        run["backend"] = backend.name
        state["runs"][run_id] = run
        submitted.append(run_id)
    write_json(paths.scheduler / "queue.json", {"queued": remaining})
    write_json(paths.scheduler / "active_jobs.json", active)
    state["next_action"] = "vibe monitor" if submitted else "vibe next"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    sync_dashboard(paths)
    return submitted


def submit_run(paths: VibePaths, run_id: str, *, dry: bool = False, backend_name: str | None = None) -> dict[str, Any]:
    state = read_json(paths.state / "state.json", {})
    run = state.get("runs", {}).get(run_id)
    if not run:
        raise ValueError(f"Unknown run: {run_id}")
    backend = get_backend(paths, backend_name)
    launch = backend.submit(run_id, dry=dry)
    write_json(paths.runs / run_id / "launch.json", launch)
    record_event(paths, "job_submitted", f"Submitted {run_id} job={launch['job_id']}", cycle_id=run.get("cycle_id", ""), run_id=run_id, status=launch["status"], payload=launch)
    return launch


def monitor(paths: VibePaths, *, auto_next: bool = False, backend_name: str | None = None) -> None:
    active = read_json(paths.scheduler / "active_jobs.json", {"active": []})
    state = read_json(paths.state / "state.json", {})
    still_active: list[dict[str, Any]] = []
    for job in active.get("active", []):
        backend = get_backend(paths, job.get("backend") or backend_name)
        poll = backend.poll(job)
        if poll.finished:
            job["finished_at"] = utc_now()
            job["status"] = poll.status
            job["poll_details"] = poll.details
            append_jsonl(paths.scheduler / "completed_jobs.jsonl", job)
            run = state.get("runs", {}).get(job["run_id"], {})
            run["status"] = poll.status
            state["runs"][job["run_id"]] = run
            record_event(paths, "job_finished", f"{job['run_id']} status={poll.status}", cycle_id=job.get("cycle_id", ""), run_id=job["run_id"], status=poll.status, payload=poll.details)
            if poll.status in {"failed", "timeout", "cancelled"}:
                apply_failure_rules(paths, state, job["run_id"], run)
        else:
            still_active.append(job)
            append_jsonl(paths.runs / job["run_id"] / "monitor.jsonl", {"checked_at": utc_now(), "status": poll.status, **poll.details})
    write_json(paths.scheduler / "active_jobs.json", {"active": still_active})
    if auto_next and not still_active and read_json(paths.scheduler / "queue.json", {"queued": []}).get("queued"):
        submit_queue(paths, dry=False, backend_name=backend_name)
        state = read_json(paths.state / "state.json", state)
    state["next_action"] = "vibe collect <run_id>" if not still_active else "vibe monitor"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    sync_dashboard(paths)


def cancel_run(paths: VibePaths, run_id: str) -> dict[str, Any]:
    active = read_json(paths.scheduler / "active_jobs.json", {"active": []})
    state = read_json(paths.state / "state.json", {})
    remaining = []
    result: dict[str, Any] = {"status": "not_active"}
    for job in active.get("active", []):
        if job.get("run_id") == run_id:
            result = get_backend(paths, job.get("backend")).cancel(job)
            job["cancelled_at"] = utc_now()
            job["status"] = "cancelled"
            job["cancel_result"] = result
            append_jsonl(paths.scheduler / "completed_jobs.jsonl", job)
            record_event(paths, "blocked", f"Cancelled {run_id}", run_id=run_id, status="cancelled", payload=result)
        else:
            remaining.append(job)
    write_json(paths.scheduler / "active_jobs.json", {"active": remaining})
    if run_id in state.get("runs", {}):
        state["runs"][run_id]["status"] = "cancelled"
        state["updated_at"] = utc_now()
        write_json(paths.state / "state.json", state)
    sync_dashboard(paths)
    return result


def dependencies_blocked(state: dict[str, Any], run: dict[str, Any]) -> bool:
    for dep in run.get("dependencies", {}).get("run_after", []):
        if state.get("runs", {}).get(dep, {}).get("status") not in {"collected", "reflected", "revised", "merged"}:
            return True
    return False


def active_gpu_count(active: list[dict[str, Any]]) -> int:
    total = 0
    for job in active:
        resources = job.get("resource_request", {}) or {}
        total += int(resources.get("gpu", 0) or 0)
    return total


def collect(paths: VibePaths, run_id: str, metric: float | None = None, trusted: bool = False, metrics_file: str | None = None) -> None:
    state = read_json(paths.state / "state.json", {})
    run = state.get("runs", {}).get(run_id)
    if not run:
        raise ValueError(f"Unknown run: {run_id}")
    evaluation = run.get("evaluation", {}) if isinstance(run.get("evaluation"), dict) else {}
    configured_metrics_file = metrics_file or evaluation.get("metrics_file_path", "")
    resolved_metrics_file = resolve_project_path(paths, configured_metrics_file) if configured_metrics_file else ""
    external_metrics = read_external_metrics(resolved_metrics_file) if resolved_metrics_file and Path(resolved_metrics_file).exists() else {}
    missing_metrics = not external_metrics and metric is None
    metric_values = external_metrics.get("metrics", external_metrics) if external_metrics else ({"primary": metric} if metric is not None else {})
    value = external_metrics.get("primary_metric", metric if metric is not None else 0.0)
    schema = evaluation.get("metrics_schema") or read_yaml(paths.leaderboard / "metrics_schema.yaml", {})
    schema_errors = [] if missing_metrics else validate_metrics_schema(metric_values, schema)
    schema_status = "missing" if missing_metrics else ("valid" if not schema_errors else "failed")
    expected_output_path = ""
    outputs = run.get("outputs", {}) if isinstance(run.get("outputs"), dict) else {}
    expected_output_path = str(outputs.get("expected_output_path", "") or "")
    resolved_expected_output = resolve_project_path(paths, expected_output_path) if expected_output_path else ""
    expected_output_exists = bool(resolved_expected_output and Path(resolved_expected_output).exists())
    provenance = build_provenance(paths, run_id)
    if trusted and not provenance_complete(provenance):
        raise RuntimeError("Trusted collection requires complete metric provenance.")
    trust_rules = evaluation.get("trust_rules", {}) if isinstance(evaluation.get("trust_rules"), dict) else {}
    if trusted and configured_metrics_file and not external_metrics and not trust_rules.get("allow_manual_metric", True):
        raise RuntimeError("Trusted collection requires metrics_file_path output; manual metric is disabled by trust_rules.")
    if trusted and expected_output_path and not expected_output_exists:
        raise RuntimeError("Trusted collection requires expected output artifact to exist.")
    if trusted and (missing_metrics or schema_errors):
        raise RuntimeError("Trusted collection requires schema-valid metrics from a file or explicit metric.")
    commands_valid = not (
        is_placeholder_command(run.get("dryrun", {}).get("command", ""))
        or is_placeholder_command(run.get("entrypoint", {}).get("command", ""))
    )
    trusted_candidate = bool(trusted and not missing_metrics and not schema_errors and commands_valid and (not expected_output_path or expected_output_exists))
    trusted_now = bool(trusted_candidate and has_revised_plan(paths, run_id))
    trust_status = "trusted" if trusted_now else "trusted_candidate" if trusted_candidate else "untrusted"
    if missing_metrics:
        trust_status = "untrusted_missing_metrics"
    elif schema_errors:
        trust_status = "untrusted_schema_failed"
    elif expected_output_path and not expected_output_exists:
        trust_status = "untrusted_missing_output"
        schema_status = "failed"
        schema_errors.append(f"expected output missing: {expected_output_path}")
    elif not commands_valid:
        trust_status = "untrusted_placeholder_command"
    metrics = {
        "run_id": run_id,
        "cycle_id": run.get("cycle_id", ""),
        "direction_id": run.get("direction_id", ""),
        "branch": run.get("branch", ""),
        "primary_metric": value,
        "metrics": metric_values,
        "trusted": trusted_now,
        "trusted_candidate": trusted_candidate,
        "trust_status": trust_status,
        "schema_status": schema_status,
        "schema_errors": schema_errors,
        "metrics_file_path": configured_metrics_file,
        "expected_output_path": expected_output_path,
        "expected_output_exists": expected_output_exists,
        "missing_metrics": missing_metrics,
        "status": "collected",
        "provenance": provenance,
    }
    write_json(paths.runs / run_id / "metrics.json", metrics)
    write_text(paths.runs / run_id / "result.md", f"# Result\n\nPrimary metric: {value}\nTrust status: {trust_status}\nSchema status: {schema_status}\n")
    append_jsonl(paths.leaderboard / "history.jsonl", metrics)
    if trusted_now:
        best = read_json(paths.leaderboard / "best.json", {})
        if is_better(paths, metrics, best):
            write_json(paths.leaderboard / "best.json", metrics)
        best_by_direction = read_json(paths.leaderboard / "best_by_direction.json", {})
        direction = run.get("direction_id", "")
        previous = best_by_direction.get(direction)
        if direction and (previous is None or is_better(paths, metrics, previous)):
            best_by_direction[direction] = metrics
            write_json(paths.leaderboard / "best_by_direction.json", best_by_direction)
    run["status"] = "collected"
    state["runs"][run_id] = run
    state["next_action"] = f"vibe reflect {run_id}"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    event = "trusted_evidence_recorded" if trusted_now else "metrics_untrusted"
    if schema_errors:
        record_event(paths, "metrics_schema_failed", "; ".join(schema_errors[:3]), cycle_id=run.get("cycle_id", ""), run_id=run_id, status=trust_status)
    record_event(paths, event, f"Collected primary={value}; trust={trust_status}; schema={schema_status}", cycle_id=run.get("cycle_id", ""), run_id=run_id, status=trust_status)
    if trusted_now:
        record_event(paths, "leaderboard_updated", f"Updated leaderboard with {run_id}", cycle_id=run.get("cycle_id", ""), run_id=run_id, status="updated")
    sync_dashboard(paths)


def parse_verdict(text: str) -> str:
    for line in text.splitlines():
        if line.strip().startswith("Verdict:"):
            return line.split("Verdict:", 1)[1].strip().split()[0]
    return ""


def paused_direction(paths: VibePaths, direction_id: str) -> bool:
    if not direction_id:
        return False
    for row in read_jsonl(paths.directions / "registry.jsonl"):
        if row.get("direction_id") == direction_id and row.get("status") in {"paused", "stopped"}:
            return True
    return False


def apply_failure_rules(paths: VibePaths, state: dict[str, Any], failed_run_id: str, run: dict[str, Any]) -> None:
    queue = read_json(paths.scheduler / "queue.json", {"queued": []})
    cancelled = set(run.get("dependencies", {}).get("cancel_if_failed", []))
    for item in queue.get("queued", []):
        if item.get("run_id") in cancelled:
            item["status"] = "cancelled_by_rule"
            item["reason"] = f"cancel_if_failed dependency {failed_run_id}"
            state.get("runs", {}).get(item["run_id"], {})["status"] = "cancelled"
            record_event(paths, "blocked", f"Cancelled {item['run_id']} after {failed_run_id} failed", run_id=item["run_id"], status="cancelled_by_rule")
    queue["queued"] = [item for item in queue.get("queued", []) if item.get("status") != "cancelled_by_rule"]
    write_json(paths.scheduler / "queue.json", queue)
    direction = run.get("direction_id", "")
    max_failed = int(load_config(paths).get("scheduler", {}).get("max_failed_runs_before_pause", 3))
    failed = [row for row in state.get("runs", {}).values() if row.get("direction_id") == direction and row.get("status") in {"failed", "timeout"}]
    if direction and len(failed) >= max_failed:
        append_jsonl(paths.directions / "registry.jsonl", {"direction_id": direction, "status": "paused", "reason": "max failed runs reached", "updated_at": utc_now()})
        record_event(paths, "direction_paused", direction, direction_id=direction, status="paused")


def resolve_project_path(paths: VibePaths, path: str | Path) -> str:
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = paths.root / candidate
    return str(candidate)


def read_external_metrics(path: str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text())
    if "primary_metric" not in data and "metrics" in data and isinstance(data["metrics"], dict):
        first = next(iter(data["metrics"].values()), 0.0)
        data["primary_metric"] = first
    if "primary_metric" not in data and "primary" in data:
        data["primary_metric"] = data["primary"]
    return data


def validate_metrics_schema(metrics: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(metrics, dict) or not metrics:
        return ["metrics are missing"]
    required = schema.get("required", []) if isinstance(schema, dict) else []
    primary_spec = schema.get("primary", {}) if isinstance(schema, dict) else {}
    if isinstance(primary_spec, dict) and primary_spec:
        required = list(required) + ["primary"]
    if not required and isinstance(schema, dict):
        required = [key for key, value in schema.items() if isinstance(value, str)]
    for name in required:
        if name not in metrics:
            errors.append(f"missing required metric `{name}`")
    typed_specs: dict[str, Any] = {}
    if isinstance(primary_spec, dict) and primary_spec.get("type"):
        typed_specs["primary"] = primary_spec.get("type")
    if isinstance(schema, dict):
        typed_specs.update({key: value for key, value in schema.items() if isinstance(value, str)})
    for name, expected in typed_specs.items():
        if name in metrics and expected == "number" and not isinstance(metrics[name], (int, float)):
            errors.append(f"`{name}` must be number")
        if name in metrics and expected == "string" and not isinstance(metrics[name], str):
            errors.append(f"`{name}` must be string")
        if name in metrics and expected in {"bool", "boolean"} and not isinstance(metrics[name], bool):
            errors.append(f"`{name}` must be boolean")
    return errors


def build_provenance(paths: VibePaths, run_id: str) -> dict[str, Any]:
    run_dir = paths.runs / run_id
    patch = run_dir / "patch.diff"
    env = {"python": platform.python_version(), "platform": platform.platform()}
    try:
        freeze = subprocess.run(["python", "-m", "pip", "freeze"], text=True, capture_output=True, check=False, timeout=20)
        env["pip_freeze_sha256"] = hashlib.sha256(freeze.stdout.encode()).hexdigest()
    except Exception:
        env["pip_freeze_sha256"] = ""
    provenance = {
        "manifest": str(run_dir / "manifest.yaml"),
        "manifest_exists": (run_dir / "manifest.yaml").exists(),
        "launch": str(run_dir / "launch.json"),
        "launch_exists": bool(read_json(run_dir / "launch.json", {})),
        "git_diff": str(patch),
        "git_diff_sha256": hashlib.sha256(patch.read_bytes()).hexdigest() if patch.exists() else "",
        "env_export": env,
        "metric_schema": str(paths.leaderboard / "metrics_schema.yaml"),
        "metric_schema_exists": (paths.leaderboard / "metrics_schema.yaml").exists(),
        "collected_at": utc_now(),
    }
    write_json(run_dir / "provenance.json", provenance)
    return provenance


def provenance_complete(provenance: dict[str, Any]) -> bool:
    return bool(provenance.get("manifest_exists") and provenance.get("launch_exists") and provenance.get("metric_schema_exists") and provenance.get("git_diff_sha256"))


def is_better(paths: VibePaths, candidate: dict[str, Any], previous: dict[str, Any]) -> bool:
    if not previous:
        return True
    schema = read_yaml(paths.leaderboard / "goals.yaml", {})
    direction = "max"
    try:
        primary = schema.get("metrics", {}).get("primary", [{}])[0]
        direction = primary.get("direction", "max")
    except Exception:
        pass
    cand = float(candidate.get("primary_metric", 0))
    prev = float(previous.get("primary_metric", 0))
    return cand <= prev if direction == "min" else cand >= prev


def has_revised_plan(paths: VibePaths, run_id: str) -> bool:
    path = paths.runs / run_id / "revised_plan.md"
    return path.exists() and bool(path.read_text().strip())


def promote_trusted_candidate(paths: VibePaths, run_id: str) -> None:
    metrics_path = paths.runs / run_id / "metrics.json"
    metrics = read_json(metrics_path, {})
    if not metrics.get("trusted_candidate") or metrics.get("trusted") or metrics.get("schema_status") != "valid" or not has_revised_plan(paths, run_id):
        return
    metrics["trusted"] = True
    metrics["trust_status"] = "trusted"
    write_json(metrics_path, metrics)
    append_jsonl(paths.leaderboard / "history.jsonl", metrics)
    best = read_json(paths.leaderboard / "best.json", {})
    if is_better(paths, metrics, best):
        write_json(paths.leaderboard / "best.json", metrics)
    best_by_direction = read_json(paths.leaderboard / "best_by_direction.json", {})
    direction = metrics.get("direction_id", "")
    previous = best_by_direction.get(direction)
    if direction and (previous is None or is_better(paths, metrics, previous)):
        best_by_direction[direction] = metrics
        write_json(paths.leaderboard / "best_by_direction.json", best_by_direction)
