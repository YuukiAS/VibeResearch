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
from .adapter_onboarding import capability_dependency_issues, find_capability
from .adapter_schema import load_adapter_manifest
from .backends import PollResult, get_backend
from .config import load_config
from .dashboard import sync_dashboard
from .directions import latest_direction_record
from .io import append_jsonl, read_json, read_jsonl, read_yaml, utc_now, write_json, write_text, write_yaml
from .manifest import validate_manifest
from .paths import VibePaths
from .real_experiments import classify_run, record_repair_issue, summarize_real_experiment_progress
from .research_manager import collect_run_evidence_if_research_linked, policy_completeness, reserve_budget
from .scheduler_approvals import fallback_requeue_command, write_fallback_requeue_request
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
    active = read_json(paths.scheduler / "active_jobs.json", {"active": []}).get("active", [])
    submitted_statuses = {"submitted", "pending", "running", "dry_submitted", "submitted_dry"}
    if any(job.get("run_id") == run_id for job in active) or run.get("status") in submitted_statuses:
        raise RuntimeError(f"Run {run_id} is already active/submitted; monitor or cancel it before rerunning dryrun")
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
    completeness = policy_completeness(paths)
    if any(item.startswith("missing budget") for item in completeness.get("issues", [])):
        raise RuntimeError("Policy completeness blocked queue: missing budget policy")
    if any(item.startswith("missing autonomy") for item in completeness.get("issues", [])):
        raise RuntimeError("Policy completeness blocked queue: missing autonomy policy")
    metadata = run.get("research_metadata", {}) if isinstance(run.get("research_metadata"), dict) else {}
    if metadata.get("hypothesis_id") or metadata.get("experiment_id"):
        if not metadata.get("budget_reservation_id"):
            reservation = reserve_budget(
                paths,
                decision_id=metadata.get("decision_id", ""),
                experiment_id=metadata.get("experiment_id", ""),
                hypothesis_id=metadata.get("hypothesis_id", ""),
                resource_units=resource_units_from_run(run),
                estimated_cost={},
                requires_long_run=False,
                confirmed=False,
            )
            if reservation.get("status") == "blocked":
                raise RuntimeError("Budget reservation blocked: " + ", ".join(reservation.get("blocked_reasons", [])))
            metadata["budget_reservation_id"] = reservation["budget_event_id"]
            run["research_metadata"] = metadata
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


def resource_units_from_run(run: dict[str, Any]) -> dict[str, Any]:
    resources = run.get("resources", {}) if isinstance(run.get("resources"), dict) else {}
    gpu = float(resources.get("gpu", 0) or 0)
    hours = walltime_hours(str(resources.get("time", "00:00:00")))
    return {
        "gpu": gpu,
        "walltime_hours": hours,
        "gpu_hours": gpu * hours,
        "cpu_hours": float(resources.get("cpus", 1) or 1) * hours,
        "memory_gb_hours": float(resources.get("mem_gb", 0) or 0) * hours,
    }


def walltime_hours(value: str) -> float:
    parts = value.split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) + int(parts[1]) / 60.0 + int(parts[2]) / 3600.0
        if len(parts) == 2:
            return int(parts[0]) / 60.0 + int(parts[1]) / 3600.0
        return float(value)
    except ValueError:
        return 0.0


def submit_queue(paths: VibePaths, *, dry: bool = False, backend_name: str | None = None) -> list[str]:
    state = read_json(paths.state / "state.json", {})
    queue = read_json(paths.scheduler / "queue.json", {"queued": []})
    active = read_json(paths.scheduler / "active_jobs.json", {"active": []})
    config = load_config(paths)
    budget = read_yaml(paths.scheduler / "budget.yaml", {}) or config.get("scheduler", {})
    max_parallel = int(budget.get("max_parallel_jobs", 3))
    max_gpu = int(budget.get("max_parallel_gpu_jobs", budget.get("max_gpu_jobs", 2)))
    submitted: list[str] = []
    remaining = []
    for item in sorted(queue.get("queued", []), key=lambda row: row.get("priority", 100)):
        run_id = item["run_id"]
        run = state.get("runs", {}).get(run_id, {})
        if not run or run.get("status") != "queued":
            continue
        run_backend_name = backend_name or (run.get("entrypoint", {}) if isinstance(run.get("entrypoint"), dict) else {}).get("type")
        backend = get_backend(paths, run_backend_name)
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
        direction_id = run.get("direction_id", "")
        if paused_direction(paths, direction_id) and auto_resume_direction_after_required_input_repair(paths, state, run):
            direction_id = run.get("direction_id", "")
        if paused_direction(paths, direction_id):
            item["status"] = "paused_direction"
            item["reason"] = f"direction {direction_id} is paused/stopped"
            remaining.append(item)
            continue
        if dependencies_blocked(state, run):
            item["status"] = "waiting_on_dependency"
            item["reason"] = "run_after dependency is not collected/reflected/revised/merged"
            remaining.append(item)
            continue
        dependency_errors = run_downstream_dependency_issues(paths, run)
        if backend.name == "slurm" and dependency_errors and not run_dependency_override_enabled(run):
            item["status"] = "waiting_on_downstream_dependency"
            item["reason"] = "; ".join(error["message"] for error in dependency_errors[:3])
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
        try:
            launch = submit_run(paths, run_id, dry=dry, backend_name=backend.name)
        except RuntimeError as exc:
            if backend.name == "slurm" and slurm_execution_environment_error(str(exc)):
                item["status"] = "execution_environment_error"
                item["reason"] = f"Slurm command failed in the current execution environment: {exc}"
                remaining.append(item)
                continue
            raise
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
    config = load_config(paths)
    still_active: list[dict[str, Any]] = []
    for job in active.get("active", []):
        backend = get_backend(paths, job.get("backend") or backend_name)
        poll = backend.poll(job)
        stale_status = stale_active_terminal_status(paths, state, job, poll)
        if stale_status:
            poll = PollResult(stale_status, True, {"reason": "stale_active_terminal_artifact", "previous_poll": poll.details})
        poll.details = carry_forward_wait_evidence(paths, job, poll.status, poll.details)
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
                if classify_run(paths, job["run_id"], run)["run_kind"] == "real_experiment":
                    record_repair_issue(paths, job["run_id"], run, f"non_counting_execution_failure:{poll.status}", poll.details)
                apply_failure_rules(paths, state, job["run_id"], run)
        elif should_requeue_to_fallback(config, job, poll.details):
            recommended = poll.details.get("wait_verdict", {}).get("recommended_partition", "")
            cancel_result = backend.cancel(job)
            job["cancelled_at"] = utc_now()
            job["status"] = "cancelled_for_fallback_requeue"
            job["cancel_result"] = cancel_result
            append_jsonl(paths.scheduler / "completed_jobs.jsonl", job)
            run = state.get("runs", {}).get(job["run_id"], {})
            force_run_partition(paths, job["run_id"], run, recommended, reason="fallback_selected_after_wait_policy")
            launch = submit_run(paths, job["run_id"], dry=False, backend_name=backend.name)
            launch["requeued_from_job_id"] = job.get("job_id", "")
            launch["requeue_reason"] = "fallback_better_available"
            still_active.append(launch)
            state = read_json(paths.state / "state.json", state)
            state.setdefault("runs", {}).setdefault(job["run_id"], {})["status"] = "submitted"
            record_event(
                paths,
                "job_requeued",
                f"Requeued {job['run_id']} to fallback partition {recommended}",
                cycle_id=job.get("cycle_id", ""),
                run_id=job["run_id"],
                status="fallback_requeued",
                payload={"previous_job": job, "new_launch": launch, "poll_details": poll.details},
            )
        else:
            job["status"] = poll.status
            job["poll_details"] = poll.details
            still_active.append(job)
            append_jsonl(paths.runs / job["run_id"] / "monitor.jsonl", {"checked_at": utc_now(), "status": poll.status, **poll.details})
            launch_path = paths.runs / job["run_id"] / "launch.json"
            launch = read_json(launch_path, job)
            launch["last_poll_status"] = poll.status
            launch["last_poll_details"] = poll.details
            write_json(launch_path, launch)
    write_json(paths.scheduler / "active_jobs.json", {"active": still_active})
    if auto_next and not still_active and read_json(paths.scheduler / "queue.json", {"queued": []}).get("queued"):
        submit_queue(paths, dry=False, backend_name=backend_name)
        state = read_json(paths.state / "state.json", state)
    state["next_action"] = "vibe collect <run_id>" if not still_active else "vibe monitor"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    summarize_real_experiment_progress(paths, write=True)
    sync_dashboard(paths)


def stale_active_terminal_status(paths: VibePaths, state: dict[str, Any], job: dict[str, Any], poll: PollResult) -> str:
    if poll.finished or poll.status != "unknown":
        return ""
    run_id = str(job.get("run_id", ""))
    run = state.get("runs", {}).get(run_id, {}) if isinstance(state.get("runs"), dict) else {}
    status = str(run.get("status", ""))
    if status in {"collected", "reflected", "revised", "merged", "finished", "failed", "timeout", "cancelled"}:
        return status
    run_dir = paths.runs / run_id
    for name in ["metrics.json", "analysis.json", "collect.json"]:
        data = read_json(run_dir / name, {})
        if isinstance(data, dict) and (data.get("schema_valid") is True or data.get("trusted") is True or data.get("metrics")):
            return "collected"
    return ""


def operator_fallback_requeue(
    paths: VibePaths,
    *,
    execute: bool = False,
    allow_outside_policy: bool = False,
    allow_carried_forward: bool = False,
    to_preferred: bool = False,
    backend_name: str | None = None,
    run_ids: list[str] | None = None,
    all_runs: bool = False,
) -> dict[str, Any]:
    selected_run_ids = set(run_ids or [])
    if execute and not selected_run_ids and not all_runs:
        raise ValueError("--execute requires --run-id <run> or --all")
    active = read_json(paths.scheduler / "active_jobs.json", {"active": []})
    state = read_json(paths.state / "state.json", {})
    rows = []
    still_active = []
    executed = []
    for job in active.get("active", []):
        details = job.get("poll_details", {}) if isinstance(job.get("poll_details"), dict) else {}
        verdict = details.get("wait_verdict", {}) if isinstance(details.get("wait_verdict"), dict) else {}
        preferred = preferred_partition_for_job(state, job)
        preferred_eligible = bool(preferred and preferred != job.get("partition") and str(job.get("status", "submitted")) in {"pending", "submitted", "dry_submitted"})
        recommended = verdict.get("recommended_partition", "")
        verdict_name = verdict.get("verdict", "")
        eligible = bool(recommended and verdict_name in {"fallback_better_available", "fallback_better_but_outside_wait_policy"})
        blocked_reason = ""
        if to_preferred:
            recommended = preferred
            verdict_name = "preferred_partition_selected"
            eligible = preferred_eligible
            if not preferred:
                blocked_reason = "missing_preferred_partition"
            elif preferred == job.get("partition"):
                blocked_reason = "already_on_preferred_partition"
            elif str(job.get("status", "submitted")) not in {"pending", "submitted", "dry_submitted"}:
                blocked_reason = "preferred_requeue_only_before_job_starts"
        if verdict_name == "fallback_better_but_outside_wait_policy" and not allow_outside_policy:
            eligible = False
            blocked_reason = "outside_wait_policy_requires_allow_outside_policy"
        if details.get("carried_forward_wait_verdict") and not allow_carried_forward:
            eligible = False
            blocked_reason = "carried_forward_wait_verdict_requires_allow_carried_forward"
        selected_for_execute = all_runs or job.get("run_id", "") in selected_run_ids
        command_allow_outside_policy = allow_outside_policy or verdict_name == "fallback_better_but_outside_wait_policy"
        command_allow_carried_forward = allow_carried_forward or bool(details.get("carried_forward_wait_verdict"))
        row = {
            "run_id": job.get("run_id", ""),
            "job_id": job.get("job_id", ""),
            "current_partition": job.get("partition", ""),
            "recommended_partition": recommended,
            "preferred_partition": preferred,
            "verdict": verdict_name,
            "eligible": eligible,
            "blocked_reason": blocked_reason,
            "execute": execute,
            "selected_for_execute": selected_for_execute,
            "executable_command": fallback_requeue_command(
                paths.root,
                str(job.get("run_id", "")),
                allow_outside_policy=command_allow_outside_policy,
                allow_carried_forward=command_allow_carried_forward,
                to_preferred=to_preferred,
                execute=True,
            ),
            "preferred_requeue_command": fallback_requeue_command(
                paths.root,
                str(job.get("run_id", "")),
                to_preferred=True,
                execute=True,
            )
            if preferred and preferred != job.get("partition")
            else "",
        }
        rows.append(row)
        if not execute or not eligible or not selected_for_execute:
            still_active.append(job)
            continue
        backend = get_backend(paths, job.get("backend") or backend_name)
        cancel_result = backend.cancel(job)
        old_status = "cancelled_for_preferred_requeue" if to_preferred else "cancelled_for_fallback"
        old = {**job, "cancelled_at": utc_now(), "status": old_status, "cancel_result": cancel_result, "operator_requeue": True}
        append_jsonl(paths.scheduler / "completed_jobs.jsonl", old)
        run = state.get("runs", {}).get(job["run_id"], {})
        force_reason = "preferred_partition_selected" if to_preferred else "fallback_selected_after_wait_policy"
        force_run_partition(paths, job["run_id"], run, recommended, reason=force_reason)
        launch = submit_run(paths, job["run_id"], dry=False, backend_name=backend.name)
        launch["requeued_from_job_id"] = job.get("job_id", "")
        launch["requeue_reason"] = verdict_name
        launch["operator_requeue"] = True
        still_active.append(launch)
        executed.append({"old_job": old, "new_launch": launch})
        event_name = "operator_preferred_requeue" if to_preferred else "operator_fallback_requeue"
        record_event(paths, event_name, f"Requeued {job['run_id']} to {recommended}", cycle_id=job.get("cycle_id", ""), run_id=job["run_id"], status="requeued", payload={"old_job": old, "new_launch": launch, "verdict": verdict})
    if execute:
        write_json(paths.scheduler / "active_jobs.json", {"active": still_active})
        state = read_json(paths.state / "state.json", state)
        for item in executed:
            run_id = item["new_launch"].get("run_id", "")
            state.setdefault("runs", {}).setdefault(run_id, {})["status"] = "submitted"
        state["next_action"] = "vibe monitor"
        state["updated_at"] = utc_now()
        write_json(paths.state / "state.json", state)
        sync_dashboard(paths)
    approval_request = None
    if not execute:
        approval_request = write_fallback_requeue_request(paths, rows)
    return {
        "execute": execute,
        "allow_outside_policy": allow_outside_policy,
        "allow_carried_forward": allow_carried_forward,
        "to_preferred": to_preferred,
        "run_ids": sorted(selected_run_ids),
        "all_runs": all_runs,
        "approval_request": approval_request,
        "candidates": rows,
        "executed": executed,
    }


def should_requeue_to_fallback(config: dict[str, Any], job: dict[str, Any], details: dict[str, Any]) -> bool:
    slurm = config.get("execution", {}).get("slurm", {}) if isinstance(config.get("execution"), dict) else {}
    if not slurm.get("auto_requeue_to_better_fallback", False):
        return False
    if details.get("carried_forward_wait_verdict") and not slurm.get("allow_requeue_from_carried_forward_wait_verdict", False):
        return False
    if job.get("backend") != "slurm":
        return False
    verdict = details.get("wait_verdict", {}) if isinstance(details.get("wait_verdict"), dict) else {}
    if verdict.get("verdict") != "fallback_better_available" or not verdict.get("recommended_partition"):
        return False
    if slurm.get("allow_fallback_outside_wait_policy", False):
        return True
    max_wait = slurm.get("max_wait_hours_for_fallback", slurm.get("max_pending_start_plus_run_hours"))
    try:
        max_wait_hours = float(max_wait or 0)
    except (TypeError, ValueError):
        max_wait_hours = 0.0
    if not max_wait_hours:
        return True
    estimate = verdict.get("recommended_estimated_start_plus_run_hours")
    if estimate is None:
        return False
    try:
        return float(estimate) <= max_wait_hours
    except (TypeError, ValueError):
        return False


def preferred_partition_for_job(state: dict[str, Any], job: dict[str, Any]) -> str:
    resources = job.get("resource_request", {}) if isinstance(job.get("resource_request"), dict) else {}
    if not resources:
        run = state.get("runs", {}).get(job.get("run_id", ""), {}) if isinstance(state.get("runs"), dict) else {}
        resources = run.get("resources", {}) if isinstance(run.get("resources"), dict) else {}
    current = str(job.get("partition") or "")
    for partition in resources.get("preferred_partitions", []) or []:
        name = str(partition)
        if name and name != current:
            return name
    return ""


def carry_forward_wait_evidence(paths: VibePaths, job: dict[str, Any], status: str, details: dict[str, Any]) -> dict[str, Any]:
    if status != "unknown" or details.get("wait_verdict"):
        return details
    if not transient_scheduler_unknown(details):
        return details
    previous = previous_wait_evidence(paths, job)
    if not previous:
        return details
    merged = dict(details)
    for key in ["wait_verdict", "wait_policy"]:
        if previous.get(key):
            merged[key] = previous[key]
    if "wait_verdict" in merged:
        merged["carried_forward_wait_verdict"] = True
        merged["carried_forward_wait_source"] = previous.get("_source", "previous_poll")
    return merged


def transient_scheduler_unknown(details: dict[str, Any]) -> bool:
    reason = str(details.get("reason", ""))
    return bool(
        details.get("poll_timeout")
        or details.get("squeue_start_timeout")
        or reason in {"slurm_query_unavailable", "slurm_accounting_record_unavailable"}
    )


def previous_wait_evidence(paths: VibePaths, job: dict[str, Any]) -> dict[str, Any]:
    prior = job.get("poll_details", {}) if isinstance(job.get("poll_details"), dict) else {}
    if prior.get("wait_verdict"):
        return {**prior, "_source": "active_jobs_previous_poll_details"}
    run_id = str(job.get("run_id", ""))
    rows = read_jsonl(paths.runs / run_id / "monitor.jsonl") if run_id else []
    for row in reversed(rows):
        if row.get("wait_verdict"):
            return {**row, "_source": "run_monitor_jsonl"}
    return {}


def force_run_partition(paths: VibePaths, run_id: str, run: dict[str, Any], partition: str, *, reason: str = "forced_partition") -> None:
    resources = run.setdefault("resources", {})
    resources["force_partition"] = partition
    resources["force_partition_reason"] = reason
    resources["preferred_partitions"] = [partition] + [p for p in resources.get("preferred_partitions", []) if p != partition]
    run["resources"] = resources
    state = read_json(paths.state / "state.json", {})
    state.setdefault("runs", {}).setdefault(run_id, {}).update(run)
    write_json(paths.state / "state.json", state)
    manifest_json = paths.runs / run_id / "manifest.json"
    manifest_yaml = paths.runs / run_id / "manifest.yaml"
    manifest = read_json(manifest_json, run)
    manifest["resources"] = resources
    write_json(manifest_json, manifest)
    write_yaml(manifest_yaml, manifest)


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


def run_downstream_dependency_issues(paths: VibePaths, run: dict[str, Any]) -> list[dict[str, Any]]:
    metadata = run.get("adapter_metadata", {}) if isinstance(run.get("adapter_metadata"), dict) else {}
    capability_id = metadata.get("capability_id", "")
    if not capability_id:
        return []
    manifest = load_adapter_manifest(paths)
    capability = find_capability(manifest, capability_id)
    if not capability:
        return []
    return capability_dependency_issues(paths, capability)


def run_dependency_override_enabled(run: dict[str, Any]) -> bool:
    metadata = run.get("adapter_metadata", {}) if isinstance(run.get("adapter_metadata"), dict) else {}
    resources = run.get("resources", {}) if isinstance(run.get("resources"), dict) else {}
    for source in [metadata, resources, run]:
        override = source.get("dependency_override") or source.get("dependency_override_confirmed") or source.get("allow_missing_dependencies")
        if isinstance(override, bool) and override:
            return True
        if isinstance(override, dict) and (override.get("confirmed") or override.get("allowed")):
            return True
        if str(override).lower() in {"true", "yes", "confirmed", "override"}:
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
    launch = read_json(paths.runs / run_id / "launch.json", {})
    dry_launch = is_dry_launch(launch)
    external_metrics = {} if dry_launch else read_external_metrics(resolved_metrics_file) if resolved_metrics_file and Path(resolved_metrics_file).exists() else {}
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
    if dry_launch:
        provenance["dry_launch_metrics_ignored"] = True
        provenance["ignored_metrics_file_path"] = configured_metrics_file
        provenance["ignored_metrics_reason"] = "dry submissions are scheduler/provenance checks and cannot produce trusted metrics"
        write_json(paths.runs / run_id / "provenance.json", provenance)
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
    collect_run_evidence_if_research_linked(paths, run_id, metrics)
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
    classification = classify_run(paths, run_id, run)
    if classification["run_kind"] == "real_experiment" and not classification["counts_toward_real_experiment_cycle"]:
        record_repair_issue(paths, run_id, run, classification["classification"], {"trust_status": trust_status, "schema_status": schema_status})
    summarize_real_experiment_progress(paths, write=True)
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
    return latest_direction_record(paths, direction_id).get("status") in {"paused", "stopped"}


def auto_resume_direction_after_required_input_repair(paths: VibePaths, state: dict[str, Any], run: dict[str, Any]) -> bool:
    direction_id = run.get("direction_id", "")
    if not direction_id:
        return False
    latest = latest_direction_record(paths, direction_id)
    if latest.get("status") != "paused" or latest.get("reason") != "max failed runs reached":
        return False
    if not same_direction_missing_required_input_history(state, run):
        return False
    required = required_input_paths(run)
    if not required or not all(Path(resolve_project_path(paths, path)).exists() for path in required):
        return False
    row = {
        "direction_id": direction_id,
        "status": "promoted",
        "reason": "auto-resumed after required input repair",
        "updated_at": utc_now(),
        "provenance": {"source": "submit_queue_required_input_repair", "run_id": run.get("run_id", ""), "required_inputs": required},
    }
    append_jsonl(paths.directions / "registry.jsonl", row)
    record_event(paths, "direction_promoted", row["reason"], direction_id=direction_id, status="promoted", payload=row)
    return True


def same_direction_missing_required_input_history(state: dict[str, Any], run: dict[str, Any]) -> bool:
    direction_id = run.get("direction_id", "")
    run_id = run.get("run_id", "")
    for other_id, other in state.get("runs", {}).items():
        if other_id == run_id or other.get("direction_id") != direction_id:
            continue
        text = " ".join(
            str(other.get(key, ""))
            for key in ["non_counting_classification", "classification", "blocked_reason", "failure_type", "failure_reason"]
        )
        if "missing_required_input" in text:
            return True
    return False


def required_input_paths(run: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    inputs = run.get("inputs", {}) if isinstance(run.get("inputs"), dict) else {}
    for source in [inputs, run.get("resources", {}) if isinstance(run.get("resources"), dict) else {}, run]:
        for key in ["required_files", "required_paths", "required_input_files", "dependency_paths"]:
            value = source.get(key)
            if isinstance(value, str):
                paths.append(value)
            elif isinstance(value, list):
                paths.extend(str(item) for item in value if str(item))
    return list(dict.fromkeys(paths))


def slurm_execution_environment_error(text: str) -> bool:
    lowered = text.lower()
    return "operation not permitted" in lowered and ("slurm" in lowered or "socket" in lowered or "stream" in lowered)


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


def is_dry_launch(launch: dict[str, Any]) -> bool:
    job_id = str(launch.get("job_id", ""))
    return launch.get("status") == "dry_submitted" or job_id.startswith("slurm-dry-")


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
