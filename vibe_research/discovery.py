"""Bounded project discovery helpers.

The bootstrap and adapter discovery paths often run against large downstream
repositories. Use an os.walk-based walker so ignored runtime directories are
pruned before descent instead of filtering after an expensive rglob traversal.
"""

from __future__ import annotations

import fnmatch
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .io import read_yaml


DEFAULT_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    ".vibe",
    ".vibe_dogfood",
    "__pycache__",
    "archive",
    "build",
    "data",
    "dist",
    "env",
    "envs",
    "external_supervisors",
    "htmlcov",
    "logs",
    "models",
    "node_modules",
    "results",
    "site-packages",
    "temp",
    "tmp",
    "venv",
}
DEFAULT_SKIP_PREFIXES = (".vibe_legacy",)


@dataclass
class DiscoveryLimits:
    max_files: int = 200
    max_dirs: int = 1000
    max_seconds: float = 5.0


@dataclass
class DiscoveryResult:
    files: list[Path] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_dirs: list[str] = field(default_factory=list)


def discovery_config(root: Path) -> dict[str, object]:
    config = read_yaml(root / ".vibe" / "config.yaml", {}) or {}
    if not isinstance(config, dict):
        return {}
    discovery = config.get("discovery", {})
    bootstrap = config.get("bootstrap", {})
    merged: dict[str, object] = {}
    if isinstance(discovery, dict):
        merged.update(discovery)
    if isinstance(bootstrap, dict) and isinstance(bootstrap.get("discovery"), dict):
        merged.update(bootstrap["discovery"])
    return merged


def configured_skip_dirs(root: Path, extra_skip_dirs: Iterable[str] | None = None) -> set[str]:
    skip = set(DEFAULT_SKIP_DIRS)
    config = discovery_config(root)
    configured = config.get("skip_dirs", [])
    if isinstance(configured, list):
        skip.update(str(item) for item in configured)
    if extra_skip_dirs:
        skip.update(str(item) for item in extra_skip_dirs)
    return skip


def configured_limits(root: Path, *, max_files: int = 200, max_dirs: int = 1000, max_seconds: float = 5.0) -> DiscoveryLimits:
    config = discovery_config(root)
    return DiscoveryLimits(
        max_files=_as_int(config.get("max_files"), max_files),
        max_dirs=_as_int(config.get("max_dirs"), max_dirs),
        max_seconds=_as_float(config.get("max_seconds"), max_seconds),
    )


def _as_int(value: object, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def should_skip_dir(path: Path, *, root: Path, skip_dirs: set[str]) -> bool:
    if path == root:
        return False
    name = path.name
    return name in skip_dirs or any(name.startswith(prefix) for prefix in DEFAULT_SKIP_PREFIXES)


def discover_files(
    root: Path,
    *,
    patterns: Iterable[str] = ("*",),
    rel_root: Path | None = None,
    skip_dirs: Iterable[str] | None = None,
    max_files: int = 200,
    max_dirs: int = 1000,
    max_seconds: float = 5.0,
) -> DiscoveryResult:
    """Return matching files under root while pruning ignored directories."""

    root = root.expanduser().resolve()
    rel_root = rel_root.expanduser().resolve() if rel_root else root
    effective_skip = configured_skip_dirs(rel_root, skip_dirs)
    limits = configured_limits(rel_root, max_files=max_files, max_dirs=max_dirs, max_seconds=max_seconds)
    pattern_list = list(patterns)
    started = time.monotonic()
    result = DiscoveryResult()
    dirs_seen = 0
    for current_text, dirnames, filenames in os.walk(root, topdown=True):
        current = Path(current_text)
        dirs_seen += 1
        if dirs_seen > limits.max_dirs:
            result.warnings.append(f"discovery truncated after {limits.max_dirs} directories under {root}")
            break
        if time.monotonic() - started > limits.max_seconds:
            result.warnings.append(f"discovery truncated after {limits.max_seconds:.1f}s under {root}")
            break
        kept_dirs = []
        for dirname in sorted(dirnames):
            child = current / dirname
            if should_skip_dir(child, root=root, skip_dirs=effective_skip):
                result.skipped_dirs.append(str(child.relative_to(rel_root)) if child.is_relative_to(rel_root) else str(child))
            else:
                kept_dirs.append(dirname)
        dirnames[:] = kept_dirs
        for filename in sorted(filenames):
            path = current / filename
            if not any(fnmatch.fnmatch(filename, pattern) for pattern in pattern_list):
                continue
            result.files.append(path)
            if len(result.files) >= limits.max_files:
                result.warnings.append(f"discovery truncated after {limits.max_files} files under {root}")
                return result
    return result


def relative_files(files: Iterable[Path], root: Path) -> list[str]:
    root = root.expanduser().resolve()
    rows = []
    for path in files:
        try:
            rows.append(str(path.resolve().relative_to(root)))
        except ValueError:
            rows.append(str(path))
    return rows
