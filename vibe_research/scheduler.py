"""Budget-aware deterministic queue and local/Slurm execution scaffolding."""

from __future__ import annotations

import shlex
import subprocess
from typing import Any

from .backends import get_backend
from .config import load_config
from .dashboard import sync_dashboard
from .io import append_jsonl, read_json, utc_now, write_json, write_text
from .manifest import validate_manifest
from .paths import VibePaths
from .timeline import record_event


def review_cycle(paths: VibePaths, cycle_id: str) -> None:
    review_path = paths.cycles / cycle_id / "portfolio_review.md"
    if not review_path.exists() or not review_path.read_text().strip() or "PENDING" in review_path.read_text():
        review_path.write_text("# Portfolio Review\n\nVerdict: APPROVE_WITH_RESOURCE_GUARDS\n\nGuards: cheap diagnostics first; respect scheduler budget.\n")
    state = read_json(paths.state / "state.json", {})
    state.setdefault("cycles", {}).setdefault(cycle_id, {})["status"] = "reviewed"
    state["status"] = "portfolio_reviewed"
    state["next_action"] = f"vibe generate-runs {cycle_id}"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "portfolio_reviewed", "APPROVE_WITH_RESOURCE_GUARDS", cycle_id=cycle_id, status="approved")
    sync_dashboard(paths)


def review_run(paths: VibePaths, run_id: str) -> None:
    state = read_json(paths.state / "state.json", {})
    run = state.get("runs", {}).get(run_id)
    if not run:
        raise ValueError(f"Unknown run: {run_id}")
    review_path = paths.runs / run_id / "review.md"
    if not review_path.exists() or not review_path.read_text().strip() or "PENDING" in review_path.read_text():
        review_path.write_text("# Run Review\n\nVerdict: APPROVE_WITH_GUARDS\n\nGuards: dry-run must pass and metric provenance must be collected.\n")
    run["status"] = "reviewed"
    state["runs"][run_id] = run
    state["next_action"] = f"vibe branch {run_id}"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "run_reviewed", "APPROVE_WITH_GUARDS", cycle_id=run.get("cycle_id", ""), run_id=run_id, direction_id=run.get("direction_id", ""), status="approved")
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
    if run.get("status") not in {"dryrun_passed", "reviewed", "branch_recorded_no_git", "branched"}:
        raise RuntimeError(f"Run {run_id} is not ready for queue; status={run.get('status')}")
    queue = read_json(paths.scheduler / "queue.json", {"queued": []})
    if run_id not in [item["run_id"] for item in queue["queued"]]:
        queue["queued"].append({"run_id": run_id, "priority": 1, "queued_at": utc_now(), "status": "queued"})
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
    budget = config.get("scheduler", {})
    max_parallel = int(budget.get("max_parallel_jobs", 3))
    max_gpu = int(budget.get("max_parallel_gpu_jobs", budget.get("max_gpu_jobs", 2)))
    backend = get_backend(paths, backend_name)
    submitted: list[str] = []
    remaining = []
    for item in sorted(queue.get("queued", []), key=lambda row: row.get("priority", 100)):
        if len(active["active"]) >= max_parallel or active_gpu_count(active["active"]) >= max_gpu:
            remaining.append(item)
            continue
        run_id = item["run_id"]
        run = state.get("runs", {}).get(run_id, {})
        if dependencies_blocked(state, run):
            item["status"] = "waiting_on_dependency"
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


def collect(paths: VibePaths, run_id: str, metric: float | None = None, trusted: bool = False) -> None:
    state = read_json(paths.state / "state.json", {})
    run = state.get("runs", {}).get(run_id)
    if not run:
        raise ValueError(f"Unknown run: {run_id}")
    value = 0.0 if metric is None else metric
    metrics = {
        "run_id": run_id,
        "cycle_id": run.get("cycle_id", ""),
        "direction_id": run.get("direction_id", ""),
        "primary_metric": value,
        "trusted": trusted,
        "status": "collected",
        "provenance": {
            "manifest": str(paths.runs / run_id / "manifest.yaml"),
            "launch": str(paths.runs / run_id / "launch.json"),
            "collected_at": utc_now(),
        },
    }
    write_json(paths.runs / run_id / "metrics.json", metrics)
    write_text(paths.runs / run_id / "result.md", f"# Result\n\nPrimary metric: {value}\nTrusted: {trusted}\n")
    append_jsonl(paths.leaderboard / "history.jsonl", metrics)
    if trusted:
        write_json(paths.leaderboard / "best.json", metrics)
    best_by_direction = read_json(paths.leaderboard / "best_by_direction.json", {})
    direction = run.get("direction_id", "")
    previous = best_by_direction.get(direction)
    if direction and (previous is None or float(value) >= float(previous.get("primary_metric", value))):
        best_by_direction[direction] = metrics
        write_json(paths.leaderboard / "best_by_direction.json", best_by_direction)
    run["status"] = "collected"
    state["runs"][run_id] = run
    state["next_action"] = f"vibe reflect {run_id}"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "metrics_collected", f"Collected primary={value}", cycle_id=run.get("cycle_id", ""), run_id=run_id, status="collected")
    record_event(paths, "leaderboard_updated", f"Updated leaderboard with {run_id}", cycle_id=run.get("cycle_id", ""), run_id=run_id, status="updated")
    sync_dashboard(paths)
