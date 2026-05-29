"""Git workflow helpers for per-run branches."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .io import append_jsonl, read_json, utc_now, write_json
from .paths import VibePaths
from .timeline import record_event


def git_available(root: Path) -> bool:
    result = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, text=True, capture_output=True, check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def git_dirty(root: Path) -> bool:
    result = subprocess.run(["git", "status", "--porcelain"], cwd=root, text=True, capture_output=True, check=False)
    return bool(result.stdout.strip()) if result.returncode == 0 else False


def create_branch(paths: VibePaths, run_id: str) -> str:
    paths.require_initialized()
    state = read_json(paths.state / "state.json", {})
    run = state.get("runs", {}).get(run_id)
    if not run:
        raise ValueError(f"Unknown run: {run_id}")
    branch = run["branch"]
    if not git_available(paths.root):
        run["status"] = "branch_recorded_no_git"
        (paths.runs / run_id / "branch.txt").write_text(branch + "\n")
        record_event(paths, "branch_created", f"Recorded branch {branch}; target repo is not a valid git worktree", run_id=run_id, status="recorded")
    else:
        if git_dirty(paths.root):
            raise RuntimeError("Target repo has uncommitted changes; branch creation is blocked.")
        result = subprocess.run(["git", "switch", "-c", branch], cwd=paths.root, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        run["status"] = "branched"
        record_event(paths, "branch_created", f"Created branch {branch}", run_id=run_id, status="ok")
    state["runs"][run_id] = run
    state["next_action"] = f"vibe dryrun {run_id}"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    active = read_json(paths.branches / "active.json", {})
    active[run_id] = {"branch": branch, "updated_at": utc_now()}
    write_json(paths.branches / "active.json", active)
    return branch


def merge_run(paths: VibePaths, run_id: str, *, override: bool = False) -> None:
    state = read_json(paths.state / "state.json", {})
    run = state.get("runs", {}).get(run_id)
    if not run:
        raise ValueError(f"Unknown run: {run_id}")
    if not override and run.get("merge_review") != "MERGE_OK":
        raise RuntimeError("Merge blocked: run requires MERGE_OK or --override.")
    append_jsonl(paths.branches / "merged.jsonl", {"run_id": run_id, "branch": run.get("branch"), "override": override, "merged_at": utc_now()})
    run["status"] = "merged"
    state["runs"][run_id] = run
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "merged", f"Merged {run_id}", run_id=run_id, status="merged")


def abandon_run(paths: VibePaths, run_id: str, reason: str = "") -> None:
    state = read_json(paths.state / "state.json", {})
    run = state.get("runs", {}).get(run_id)
    if not run:
        raise ValueError(f"Unknown run: {run_id}")
    append_jsonl(paths.branches / "abandoned.jsonl", {"run_id": run_id, "branch": run.get("branch"), "reason": reason, "abandoned_at": utc_now()})
    run["status"] = "abandoned"
    state["runs"][run_id] = run
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "abandoned", reason or f"Abandoned {run_id}", run_id=run_id, status="abandoned")

