"""External resource acquisition with VibeResearch provenance."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
from typing import Any

from .io import append_jsonl, ensure_dir, read_jsonl, slugify, utc_now
from .paths import VibePaths
from .timeline import record_event


def clone_external_repo(paths: VibePaths, url: str, *, name: str = "", dry_run: bool = False) -> dict[str, Any]:
    paths.require_initialized()
    root = ensure_dir(paths.research / "external_repos")
    safe_name = slugify(name or repo_name_from_url(url) or "external_repo")
    dest = unique_destination(root, safe_name)
    row = {
        "created_at": utc_now(),
        "url": url,
        "name": dest.name,
        "path": str(dest.relative_to(paths.root)),
        "status": "planned" if dry_run else "cloning",
        "commit": "",
        "error": "",
    }
    if dry_run:
        append_jsonl(paths.research / "external_repos.jsonl", row)
        return row
    try:
        completed = subprocess.run(["git", "clone", "--depth", "1", url, str(dest)], cwd=paths.root, text=True, capture_output=True, check=False, timeout=300)
        if completed.returncode != 0:
            row["status"] = "failed"
            row["error"] = (completed.stderr or completed.stdout).strip()[:2000]
        else:
            row["status"] = "cloned"
            row["commit"] = git_commit(dest)
    except Exception as exc:
        row["status"] = "failed"
        row["error"] = str(exc)
    append_jsonl(paths.research / "external_repos.jsonl", row)
    record_event(paths, "external_repo_clone", f"{row['status']}: {url}", status=row["status"], payload=row)
    return row


def repo_name_from_url(url: str) -> str:
    text = url.rstrip("/")
    name = text.rsplit("/", 1)[-1]
    name = re.sub(r"\.git$", "", name)
    return name


def unique_destination(root: Path, base_name: str) -> Path:
    existing = {row.get("name", "") for row in read_jsonl(root.parent / "external_repos.jsonl")}
    candidate = root / base_name
    if not candidate.exists() and candidate.name not in existing:
        return candidate
    index = 2
    while True:
        candidate = root / f"{base_name}-{index}"
        if not candidate.exists() and candidate.name not in existing:
            return candidate
        index += 1


def git_commit(repo: Path) -> str:
    completed = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, text=True, capture_output=True, check=False, timeout=10)
    return completed.stdout.strip() if completed.returncode == 0 else ""
