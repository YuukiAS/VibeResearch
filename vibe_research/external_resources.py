"""External resource acquisition with VibeResearch provenance."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
from typing import Any

from .io import append_jsonl, ensure_dir, read_jsonl, slugify, utc_now, write_json, write_text
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


def analyze_external_repo(paths: VibePaths, name: str) -> dict[str, Any]:
    rows = read_jsonl(paths.research / "external_repos.jsonl")
    row = next((item for item in reversed(rows) if item.get("name") == name or Path(str(item.get("path", ""))).name == name), None)
    if not row:
        raise ValueError(f"Unknown external repo: {name}")
    repo_path = paths.root / str(row.get("path", ""))
    if not repo_path.exists() or not repo_path.is_dir():
        raise ValueError(f"External repo path is missing: {repo_path}")
    analysis_dir = ensure_dir(paths.research / "external_repo_analyses")
    top_level = sorted(item.name for item in repo_path.iterdir())[:50]
    setup_files = [item for item in top_level if item in {"pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "environment.yml", "environment.yaml"}]
    package_roots = sorted(str(path.relative_to(repo_path)) for path in repo_path.glob("*/__init__.py"))[:30]
    entrypoints = sorted(
        str(path.relative_to(repo_path))
        for pattern in ["*train*.py", "*infer*.py", "*eval*.py", "*test*.py"]
        for path in repo_path.rglob(pattern)
        if ".git" not in path.parts
    )[:50]
    readme = first_readme(repo_path)
    readme_excerpt = readme.read_text(errors="ignore")[:4000] if readme else ""
    analysis = {
        "created_at": utc_now(),
        "name": row.get("name", name),
        "source_repo_path": row.get("path", ""),
        "source_url": row.get("url", ""),
        "commit": row.get("commit", ""),
        "top_level": top_level,
        "setup_files": setup_files,
        "package_roots": package_roots,
        "likely_entrypoints": entrypoints,
        "readme_excerpt": readme_excerpt,
        "risk_notes": [
            "read-only static scan only; external code was not imported, installed, or executed",
            "entrypoint candidates require adapter review and contract tests before use",
        ],
        "safe_integration_policy": "Do not execute external repository code until commands, dependencies, inputs, outputs, and metrics schemas are adapter-linted and contract-tested.",
    }
    json_path = analysis_dir / f"{slugify(str(analysis['name']))}.json"
    md_path = analysis_dir / f"{slugify(str(analysis['name']))}.md"
    write_json(json_path, analysis)
    write_text(md_path, render_external_repo_analysis(analysis))
    record = {**analysis, "analysis_json": str(json_path.relative_to(paths.root)), "analysis_md": str(md_path.relative_to(paths.root))}
    append_jsonl(paths.research / "external_repo_analyses.jsonl", record)
    record_event(paths, "external_repo_analysis", str(analysis["name"]), status="analyzed", payload=record)
    return record


def render_external_repo_analysis(analysis: dict[str, Any]) -> str:
    lines = [
        f"# External Repo Analysis: {analysis.get('name', '')}",
        "",
        f"- Source: {analysis.get('source_url', '')}",
        f"- Path: `{analysis.get('source_repo_path', '')}`",
        f"- Commit: `{analysis.get('commit', '')}`",
        "",
        "## Top-Level Layout",
        *[f"- `{item}`" for item in analysis.get("top_level", [])],
        "",
        "## Setup Files",
    ]
    lines.extend([f"- `{item}`" for item in analysis.get("setup_files", [])] or ["- none detected"])
    lines.extend(["", "## Package Roots"])
    lines.extend([f"- `{item}`" for item in analysis.get("package_roots", [])] or ["- none detected"])
    lines.extend(["", "## Likely Entrypoints"])
    lines.extend([f"- `{item}`" for item in analysis.get("likely_entrypoints", [])] or ["- none detected"])
    lines.extend(
        [
            "",
            "## README Excerpt",
            analysis.get("readme_excerpt", "") or "none",
            "",
            "## Safe Integration Policy",
            analysis.get("safe_integration_policy", ""),
            "",
            "## Risk Notes",
        ]
    )
    lines.extend([f"- {item}" for item in analysis.get("risk_notes", [])])
    return "\n".join(lines) + "\n"


def first_readme(repo_path: Path) -> Path | None:
    for name in ["README.md", "README.rst", "README.txt", "README"]:
        path = repo_path / name
        if path.exists() and path.is_file():
            return path
    return None
