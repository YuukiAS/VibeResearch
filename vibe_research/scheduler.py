"""Budget-aware deterministic queue and local/Slurm execution scaffolding."""

from __future__ import annotations

import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .dashboard import sync_dashboard
from .io import append_jsonl, read_json, utc_now, write_json, write_text
from .paths import VibePaths
from .timeline import record_event


def review_cycle(paths: VibePaths, cycle_id: str) -> None:
    review_path = paths.cycles / cycle_id / "portfolio_review.md"
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
    (paths.runs / run_id / "review.md").write_text("# Run Review\n\nVerdict: APPROVE_WITH_GUARDS\n\nGuards: dry-run must pass and metric provenance must be collected.\n")
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


def submit_queue(paths: VibePaths, *, dry: bool = False) -> list[str]:
    state = read_json(paths.state / "state.json", {})
    queue = read_json(paths.scheduler / "queue.json", {"queued": []})
    active = read_json(paths.scheduler / "active_jobs.json", {"active": []})
    max_parallel = 3
    submitted: list[str] = []
    remaining = []
    for item in queue.get("queued", []):
        if len(active["active"]) >= max_parallel:
            remaining.append(item)
            continue
        run_id = item["run_id"]
        run = state.get("runs", {}).get(run_id, {})
        launch = submit_run(paths, run_id, dry=dry)
        active["active"].append(launch)
        run["status"] = "submitted_dry" if dry else "submitted"
        state["runs"][run_id] = run
        submitted.append(run_id)
    write_json(paths.scheduler / "queue.json", {"queued": remaining})
    write_json(paths.scheduler / "active_jobs.json", active)
    state["next_action"] = "vibe monitor" if submitted else "vibe next"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    sync_dashboard(paths)
    return submitted


def submit_run(paths: VibePaths, run_id: str, *, dry: bool = False) -> dict[str, Any]:
    state = read_json(paths.state / "state.json", {})
    run = state.get("runs", {}).get(run_id)
    if not run:
        raise ValueError(f"Unknown run: {run_id}")
    command = run.get("entrypoint", {}).get("command") or "python -c 'print(\"run\")'"
    launch = {
        "run_id": run_id,
        "cycle_id": run.get("cycle_id", ""),
        "command": command,
        "submitted_at": utc_now(),
        "status": "dry_submitted" if dry else "submitted",
        "job_id": f"local-{run_id}" if dry else "",
        "log_path": str(paths.runs / run_id / "artifacts" / "run.log"),
    }
    if not dry:
        log_path = Path(launch["log_path"])
        with log_path.open("w") as handle:
            proc = subprocess.Popen(shlex.split(command), cwd=paths.root, stdout=handle, stderr=subprocess.STDOUT)
        launch["pid"] = proc.pid
        launch["job_id"] = f"pid-{proc.pid}"
    write_json(paths.runs / run_id / "launch.json", launch)
    record_event(paths, "job_submitted", f"Submitted {run_id} job={launch['job_id']}", cycle_id=run.get("cycle_id", ""), run_id=run_id, status=launch["status"], payload=launch)
    return launch


def monitor(paths: VibePaths) -> None:
    active = read_json(paths.scheduler / "active_jobs.json", {"active": []})
    state = read_json(paths.state / "state.json", {})
    still_active: list[dict[str, Any]] = []
    for job in active.get("active", []):
        pid = job.get("pid")
        finished = False
        if pid:
            proc = subprocess.run(["kill", "-0", str(pid)], text=True, capture_output=True, check=False)
            finished = proc.returncode != 0
        else:
            finished = True
        if finished:
            job["finished_at"] = utc_now()
            job["status"] = "finished"
            append_jsonl(paths.scheduler / "completed_jobs.jsonl", job)
            run = state.get("runs", {}).get(job["run_id"], {})
            run["status"] = "finished"
            state["runs"][job["run_id"]] = run
            record_event(paths, "job_finished", f"Finished {job['run_id']}", cycle_id=job.get("cycle_id", ""), run_id=job["run_id"], status="finished")
        else:
            still_active.append(job)
            append_jsonl(paths.runs / job["run_id"] / "monitor.jsonl", {"checked_at": utc_now(), "status": "running", "pid": pid})
    write_json(paths.scheduler / "active_jobs.json", {"active": still_active})
    state["next_action"] = "vibe collect <run_id>" if not still_active else "vibe monitor"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    sync_dashboard(paths)


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
    run["status"] = "collected"
    state["runs"][run_id] = run
    state["next_action"] = f"vibe reflect {run_id}"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "metrics_collected", f"Collected primary={value}", cycle_id=run.get("cycle_id", ""), run_id=run_id, status="collected")
    record_event(paths, "leaderboard_updated", f"Updated leaderboard with {run_id}", cycle_id=run.get("cycle_id", ""), run_id=run_id, status="updated")
    sync_dashboard(paths)

