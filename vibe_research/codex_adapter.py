"""Codex collaboration boundary.

This module does not call Codex directly. It builds prompt packets and records
where Codex-produced artifacts should be written, keeping execution under the
deterministic runner/scheduler.
"""

from __future__ import annotations

from pathlib import Path

from .paths import VibePaths


def prompt_packet(paths: VibePaths, role: str, target_id: str = "") -> str:
    prompt_path = paths.prompts / f"{role}.md"
    prompt = prompt_path.read_text() if prompt_path.exists() else f"# {role}\n"
    return f"""{prompt}

## Deterministic Boundary
Write artifacts only. Do not submit long-running jobs. The local runner owns
dry-run, queue, submit, monitor, collect, metrics, and provenance.

## Target
{target_id}
"""


def artifact_path(paths: VibePaths, role: str, target_id: str) -> Path:
    if target_id.startswith("r"):
        return paths.runs / target_id / f"{role}.md"
    if target_id.startswith("c"):
        return paths.cycles / target_id / f"{role}.md"
    return paths.vibe / f"{role}.md"

