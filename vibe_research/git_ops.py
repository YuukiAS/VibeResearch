"""Git workflow helpers for per-run branches."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .io import append_jsonl, read_json, utc_now, write_json, write_text
from .paths import VibePaths
from .timeline import record_event


def git_available(root: Path) -> bool:
    result = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=root, text=True, capture_output=True, check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def git_dirty(root: Path) -> bool:
    result = subprocess.run(["git", "status", "--porcelain"], cwd=root, text=True, capture_output=True, check=False)
    return bool(result.stdout.strip()) if result.returncode == 0 else False


def git_current_branch(root: Path) -> str:
    result = subprocess.run(["git", "branch", "--show-current"], cwd=root, text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def git_diff_text(root: Path) -> str:
    result = subprocess.run(["git", "diff", "--binary"], cwd=root, text=True, capture_output=True, check=False)
    return result.stdout if result.returncode == 0 else ""


def changed_paths_from_diff(diff_text: str) -> list[str]:
    paths: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            if len(parts) >= 4:
                path = parts[3][2:] if parts[3].startswith("b/") else parts[3]
                paths.append(path)
    return paths


def protected_diff_paths(diff_text: str) -> list[str]:
    protected_prefixes = [".git", ".vibe/state", ".vibe/scheduler", ".vibe/leaderboard/best.json"]
    changed = changed_paths_from_diff(diff_text)
    return [path for path in changed if any(path == prefix or path.startswith(prefix + "/") for prefix in protected_prefixes)]


def adapter_run_requires_no_patch(run: dict) -> bool:
    adapter_metadata = run.get("adapter_metadata", {}) if isinstance(run.get("adapter_metadata"), dict) else {}
    return bool(adapter_metadata.get("capability_id")) and run.get("run_kind") == "real_experiment"


def create_branch(paths: VibePaths, run_id: str) -> str:
    paths.require_initialized()
    state = read_json(paths.state / "state.json", {})
    run = state.get("runs", {}).get(run_id)
    if not run:
        raise ValueError(f"Unknown run: {run_id}")
    branch = run["branch"]
    if adapter_run_requires_no_patch(run):
        run["status"] = "patched"
        (paths.runs / run_id / "branch.txt").write_text(f"{branch}\nbranch_skipped=adapter_backed_run\n")
        write_text(paths.runs / run_id / "patch.diff", "")
        record_event(paths, "branch_skipped", f"Skipped branch for adapter-backed run {run_id}", run_id=run_id, status="patched")
        state["runs"][run_id] = run
        state["next_action"] = f"vibe dryrun {run_id}"
        state["updated_at"] = utc_now()
        write_json(paths.state / "state.json", state)
        return branch
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
    state["next_action"] = f"vibe patch {run_id}"
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


def merge_review(paths: VibePaths, run_id: str) -> str:
    state = read_json(paths.state / "state.json", {})
    run = state.get("runs", {}).get(run_id)
    if not run:
        raise ValueError(f"Unknown run: {run_id}")
    required = [
        "proposal.md",
        "review.md",
        "manifest.json",
        "patch.diff",
        "dryrun.json",
        "launch.json",
        "metrics.json",
        "reflect.md",
        "revised_plan.md",
    ]
    missing = [name for name in required if not (paths.runs / run_id / name).exists()]
    cycle_id = run.get("cycle_id", "")
    if cycle_id and not (paths.cycles / cycle_id / "cycle_reflect.md").exists():
        missing.append(f"cycles/{cycle_id}/cycle_reflect.md")
    metrics = read_json(paths.runs / run_id / "metrics.json", {})
    verdict = "MERGE_OK" if not missing and metrics.get("trusted") and metrics.get("provenance") else "MERGE_BLOCKED"
    text = f"# Merge Review for {run_id}\n\nVerdict: {verdict}\n\nMissing: {', '.join(missing) or 'none'}\nTrusted metrics: {bool(metrics.get('trusted'))}\nProvenance: {bool(metrics.get('provenance'))}\n"
    write_text(paths.runs / run_id / "merge_review.md", text)
    run["merge_review"] = verdict
    state["runs"][run_id] = run
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "merge_review_done", verdict, run_id=run_id, status=verdict)
    return verdict


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
