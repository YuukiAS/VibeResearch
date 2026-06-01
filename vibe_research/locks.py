"""Target-scoped advancing command locks."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import os
import time
from typing import Any, Iterator

from .io import ensure_dir, read_json, utc_now, write_json
from .paths import VibePaths


def advance_lock_path(paths: VibePaths) -> Path:
    return paths.state / "advance.lock"


def active_advance_lock(paths: VibePaths) -> dict[str, Any]:
    lock = read_json(advance_lock_path(paths), {})
    if not isinstance(lock, dict) or not lock:
        return {}
    lock["pid_alive"] = pid_alive(int(lock.get("pid", 0) or 0))
    return lock


@contextmanager
def advancing_lock(paths: VibePaths, *, command: str, current_action: str = "starting", force: bool = False, stale_seconds: int = 21600) -> Iterator[dict[str, Any]]:
    ensure_dir(paths.state)
    lock_path = advance_lock_path(paths)
    owner = {"pid": os.getpid(), "started_at": utc_now(), "started_monotonic": time.time(), "command": command, "target_root": str(paths.root.resolve()), "current_action": current_action}
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w") as handle:
                import json

                handle.write(json.dumps(owner, sort_keys=True) + "\n")
            break
        except FileExistsError:
            existing = active_advance_lock(paths)
            if not existing.get("pid_alive") or (force and lock_is_stale(existing, stale_seconds)):
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass
                continue
            raise RuntimeError(render_lock_error(existing))
    try:
        yield owner
    finally:
        existing = read_json(lock_path, {})
        if existing.get("pid") == os.getpid() and existing.get("command") == command:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def update_advance_lock(paths: VibePaths, *, current_action: str) -> None:
    lock = read_json(advance_lock_path(paths), {})
    if not lock:
        return
    lock["current_action"] = current_action
    lock["updated_at"] = utc_now()
    write_json(advance_lock_path(paths), lock)


def lock_is_stale(lock: dict[str, Any], stale_seconds: int) -> bool:
    if not lock:
        return True
    if not lock.get("pid_alive"):
        return True
    try:
        started = float(lock.get("started_monotonic", 0.0) or 0.0)
    except (TypeError, ValueError):
        return False
    return bool(started and (time.time() - started) > stale_seconds)


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def render_lock_error(lock: dict[str, Any]) -> str:
    return (
        "advance_lock_active: another advancing command is running for this target "
        f"(pid={lock.get('pid')}, command={lock.get('command')}, current_action={lock.get('current_action')}, "
        f"started_at={lock.get('started_at')}). Wait for it to finish, inspect `vibe daemon status`, "
        "or retry with an explicit force override after verifying the lock is stale."
    )
