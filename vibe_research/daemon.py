"""tmux-backed supervisor helpers."""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .config import load_config
from .io import read_json, read_jsonl, utc_now, write_json
from .paths import VibePaths


def daemon_session(paths: VibePaths) -> str:
    config = load_config(paths)
    prefix = config.get("execution", {}).get("local", {}).get("tmux_session_prefix", "vibe")
    return f"{prefix}-{paths.root.name}-daemon".replace("_", "-")[:80]


def daemon_status(paths: VibePaths) -> dict[str, Any]:
    session = daemon_session(paths)
    queue = read_json(paths.scheduler / "queue.json", {"queued": []}).get("queued", [])
    active = read_json(paths.scheduler / "active_jobs.json", {"active": []}).get("active", [])
    completed = read_jsonl(paths.scheduler / "completed_jobs.jsonl")
    state = read_json(paths.state / "state.json", {})
    next_collect = [run_id for run_id, run in state.get("runs", {}).items() if run.get("status") in {"finished", "submitted_dry"}]
    base = {"session": session, "queued_jobs": len(queue), "active_jobs": len(active), "completed_jobs": len(completed), "next_collection_runs": next_collect}
    if not shutil.which("tmux"):
        return {**base, "available": False, "running": False, "reason": "tmux not found"}
    result = subprocess.run(["tmux", "has-session", "-t", session], text=True, capture_output=True, check=False)
    return {**base, "available": True, "running": result.returncode == 0}


def daemon_start(
    paths: VibePaths,
    *,
    interval: int | None = None,
    auto_next: bool = True,
    mode: str = "auto-cycle",
    offline: bool = False,
    dry_submit: bool = True,
    max_steps: int = 30,
) -> dict[str, Any]:
    status = daemon_status(paths)
    if not status["available"]:
        raise RuntimeError(status["reason"])
    if status["running"]:
        return status
    if mode not in {"auto-cycle", "monitor"}:
        raise ValueError("mode must be auto-cycle or monitor")
    config = load_config(paths)
    interval = interval or int(config.get("monitor", {}).get("loop_interval_seconds", 300))
    log_path = paths.dashboard / "daemon.log"
    target = shlex.quote(str(paths.root))
    python = shlex.quote(sys.executable)
    if mode == "monitor":
        loop_command = f"{python} -m vibe_research.cli monitor --target {target} --loop --interval {interval}" + (" --auto-next" if auto_next else "")
    else:
        loop_command = (
            "while true; do "
            f"{python} -m vibe_research.cli auto-cycle --target {target} --max-steps {max_steps}"
            + (" --offline" if offline else "")
            + (" --dry-submit" if dry_submit else " --real-submit")
            + f"; {python} -m vibe_research.cli status --target {target}; sleep {interval}; done"
        )
    command = f"cd {target} && {loop_command} >> {shlex.quote(str(log_path))} 2>&1"
    shell = "/usr/bin/bash" if Path("/usr/bin/bash").exists() else "sh"
    result = subprocess.run(["tmux", "new-session", "-d", "-s", status["session"], shell, "-lc", command], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    write_json(
        paths.state / "daemon.json",
        {
            "session": status["session"],
            "started_at": utc_now(),
            "interval": interval,
            "auto_next": auto_next,
            "mode": mode,
            "offline": offline,
            "dry_submit": dry_submit,
            "max_steps": max_steps,
            "interpreter": sys.executable,
            "shell": shell,
        },
    )
    return daemon_status(paths)


def daemon_stop(paths: VibePaths) -> dict[str, Any]:
    status = daemon_status(paths)
    if status.get("running"):
        result = subprocess.run(["tmux", "kill-session", "-t", status["session"]], text=True, capture_output=True, check=False)
        status["stop_returncode"] = result.returncode
        status["stderr"] = result.stderr
    return status
