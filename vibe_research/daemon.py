"""tmux-backed supervisor helpers."""

from __future__ import annotations

import shlex
import hashlib
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
    target_hash = hashlib.sha1(str(paths.root.resolve()).encode("utf-8")).hexdigest()[:8]
    return f"{prefix}-{paths.root.name}-{target_hash}-daemon".replace("_", "-")[:80]


def daemon_status(paths: VibePaths) -> dict[str, Any]:
    session = daemon_session(paths)
    target_root = str(paths.root.resolve())
    daemon_state = read_json(paths.state / "daemon.json", {})
    recorded_target_root = str(daemon_state.get("target_root", ""))
    queue = read_json(paths.scheduler / "queue.json", {"queued": []}).get("queued", [])
    active = read_json(paths.scheduler / "active_jobs.json", {"active": []}).get("active", [])
    completed = read_jsonl(paths.scheduler / "completed_jobs.jsonl")
    state = read_json(paths.state / "state.json", {})
    next_action = str(state.get("next_action", "") or "")
    next_collect = [
        run_id
        for run_id, run in state.get("runs", {}).items()
        if run.get("status") in {"finished", "submitted_dry"} and not non_counting_run(run)
    ]
    actionable = actionable_next_action(next_action)
    autonomous_blockers = daemon_autonomy_blockers(
        mode=str(daemon_state.get("mode", "")),
        auto_next=daemon_state.get("auto_next"),
        dry_submit=daemon_state.get("dry_submit"),
        actionable_next=actionable,
    )
    base = {
        "session": session,
        "target_root": target_root,
        "recorded_target_root": recorded_target_root,
        "mode": daemon_state.get("mode", ""),
        "interval": daemon_state.get("interval"),
        "auto_next": daemon_state.get("auto_next"),
        "offline": daemon_state.get("offline"),
        "dry_submit": daemon_state.get("dry_submit"),
        "max_steps": daemon_state.get("max_steps"),
        "queued_jobs": len(queue),
        "active_jobs": len(active),
        "completed_jobs": len(completed),
        "next_action": next_action,
        "actionable_next_action": actionable,
        "autonomous_progress_ok": not autonomous_blockers,
        "autonomous_progress_blockers": autonomous_blockers,
        "next_collection_runs": next_collect,
    }
    if not shutil.which("tmux"):
        return {**base, "available": False, "running": False, "reason": "tmux not found"}
    result = subprocess.run(["tmux", "has-session", "-t", session], text=True, capture_output=True, check=False)
    running = result.returncode == 0
    if not running:
        return {**base, "available": True, "running": False, "target_match": True}
    pane_current_path = tmux_output(["tmux", "display-message", "-p", "-t", session, "#{pane_current_path}"])
    pane_current_command = tmux_output(["tmux", "display-message", "-p", "-t", session, "#{pane_current_command}"])
    pane_text = tmux_output(["tmux", "capture-pane", "-pt", session, "-S", "-20"])
    command_target_root = parse_command_target(pane_text)
    sentinel_target_root = parse_daemon_sentinel(pane_text)
    pane_match = not pane_current_path or same_path(pane_current_path, target_root)
    recorded_match = not recorded_target_root or same_path(recorded_target_root, target_root)
    command_match = not command_target_root or same_path(command_target_root, target_root)
    sentinel_match = not sentinel_target_root or same_path(sentinel_target_root, target_root)
    return {
        **base,
        "available": True,
        "running": True,
        "pane_current_path": pane_current_path,
        "pane_current_command": pane_current_command,
        "command_target_root": command_target_root,
        "sentinel_target_root": sentinel_target_root,
        "managed_loop": bool(sentinel_target_root and sentinel_match),
        "target_match": pane_match and recorded_match and command_match and sentinel_match,
    }


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
    config = load_config(paths)
    interval = interval or int(config.get("monitor", {}).get("loop_interval_seconds", 300))
    status = daemon_status(paths)
    if not status["available"]:
        raise RuntimeError(status["reason"])
    if status["running"]:
        if not status.get("target_match", True):
            raise RuntimeError(
                "target_mismatch: existing daemon session "
                f"{status['session']} is not bound to {paths.root.resolve()}"
            )
        requested = {"mode": mode, "interval": interval, "auto_next": auto_next, "offline": offline, "dry_submit": dry_submit, "max_steps": max_steps}
        mismatch = daemon_option_mismatch(status, requested)
        if mismatch:
            raise RuntimeError("daemon_option_mismatch: stop the existing daemon before changing " + ", ".join(mismatch))
        return status
    if mode not in {"auto-cycle", "monitor"}:
        raise ValueError("mode must be auto-cycle or monitor")
    log_path = paths.dashboard / "daemon.log"
    target = shlex.quote(str(paths.root))
    python = shlex.quote(sys.executable)
    framework_root = Path(__file__).resolve().parent.parent
    pythonpath = f"PYTHONPATH={shlex.quote(str(framework_root))}:$PYTHONPATH"
    sentinel = f"echo VIBE_DAEMON_TARGET={target}"
    if mode == "monitor":
        loop_command = f"{sentinel}; {pythonpath} {python} -m vibe_research.cli monitor --target {target} --loop --interval {interval}" + (" --auto-next" if auto_next else "")
    else:
        loop_command = (
            f"{sentinel}; while true; do "
            f"{pythonpath} {python} -m vibe_research.cli auto-cycle --target {target} --max-steps {max_steps}"
            + (" --offline" if offline else "")
            + (" --dry-submit" if dry_submit else " --real-submit")
            + f"; {pythonpath} {python} -m vibe_research.cli status --target {target}; sleep {interval}; done"
        )
    command = f"cd {target} && {loop_command} >> {shlex.quote(str(log_path))} 2>&1"
    shell = "/usr/bin/bash" if Path("/usr/bin/bash").exists() else "sh"
    result = subprocess.run(["tmux", "new-session", "-d", "-s", status["session"], "-c", str(paths.root.resolve()), shell, "-lc", command], text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    write_json(
        paths.state / "daemon.json",
        {
            "session": status["session"],
            "target_root": str(paths.root.resolve()),
            "started_at": utc_now(),
            "interval": interval,
            "auto_next": auto_next,
            "mode": mode,
            "offline": offline,
            "dry_submit": dry_submit,
            "max_steps": max_steps,
            "interpreter": sys.executable,
            "framework_root": str(framework_root),
            "shell": shell,
        },
    )
    return daemon_status(paths)


def tmux_output(args: list[str]) -> str:
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def parse_command_target(text: str) -> str:
    tokens = shlex.split(text.replace("\n", " ")) if text.strip() else []
    for index, token in enumerate(tokens[:-1]):
        if token == "--target":
            return tokens[index + 1]
    return ""


def parse_daemon_sentinel(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if "VIBE_DAEMON_TARGET=" in stripped:
            return stripped.split("VIBE_DAEMON_TARGET=", 1)[1].strip().strip("'\"")
    return ""


def same_path(left: str, right: str) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except Exception:
        return left == right


def non_counting_run(run: dict[str, Any]) -> bool:
    return bool(run.get("non_counting_classification") or run.get("classification"))


def daemon_option_mismatch(status: dict[str, Any], requested: dict[str, Any]) -> list[str]:
    mismatch = []
    for key, value in requested.items():
        recorded = status.get(key)
        if recorded in {"", None}:
            continue
        if recorded != value:
            mismatch.append(key)
    return mismatch


def daemon_stop(paths: VibePaths) -> dict[str, Any]:
    status = daemon_status(paths)
    if status.get("running"):
        result = subprocess.run(["tmux", "kill-session", "-t", status["session"]], text=True, capture_output=True, check=False)
        status["stop_returncode"] = result.returncode
        status["stderr"] = result.stderr
    return {"before": status, "after": daemon_status(paths)}


def daemon_autonomy_audit(paths: VibePaths, *, expect_autonomous: bool = True, expect_real_submit: bool = False) -> dict[str, Any]:
    status = daemon_status(paths)
    blockers = []
    if expect_autonomous:
        blockers.extend(status.get("autonomous_progress_blockers", []))
        if not status.get("running"):
            blockers.append("daemon_not_running")
    if expect_real_submit and status.get("dry_submit") is True:
        blockers.append("daemon_dry_submit_enabled_while_real_submit_expected")
    result = {
        "created_at": utc_now(),
        "ok": not blockers,
        "blockers": blockers,
        "status": status,
        "restart_recommendation": "",
    }
    if blockers:
        result["restart_recommendation"] = "vibe daemon stop --target <repo> && vibe daemon start --target <repo> --mode auto-cycle --auto-next --real-submit --interval 300"
    return result


def actionable_next_action(next_action: str) -> bool:
    text = next_action.strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered in {"none", "noop", "done", "complete"}:
        return False
    if lowered.startswith(("wait", "blocked", "manual", "no ")):
        return False
    return lowered.startswith("vibe ")


def daemon_autonomy_blockers(*, mode: str, auto_next: Any, dry_submit: Any, actionable_next: bool) -> list[str]:
    if not actionable_next:
        return []
    blockers = []
    if mode == "monitor":
        blockers.append("daemon_monitor_only_while_next_action_is_actionable")
    if auto_next is False:
        blockers.append("daemon_auto_next_false_while_next_action_is_actionable")
    if dry_submit is True:
        blockers.append("daemon_dry_submit_true_while_next_action_is_actionable")
    return blockers
