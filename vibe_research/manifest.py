"""Run manifest validation and loading."""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Any

from .adapters import is_placeholder_command
from .io import read_json
from .models import RunManifest
from .paths import VibePaths


@dataclass
class ValidationIssue:
    level: str
    message: str


PROTECTED_PATHS = {".git", ".vibe/state", ".vibe/scheduler", ".vibe/leaderboard/best.json"}
DANGEROUS_BINS = {"rm", "sudo", "su", "mkfs", "dd", "shutdown", "reboot", "poweroff", "halt"}


def load_manifest(paths: VibePaths, run_id: str) -> RunManifest:
    data = read_json(paths.runs / run_id / "manifest.json", {})
    if not data:
        state = read_json(paths.state / "state.json", {})
        data = state.get("runs", {}).get(run_id, {})
    if not data:
        raise ValueError(f"Unknown run manifest: {run_id}")
    return RunManifest.model_validate(data)


def validate_manifest(paths: VibePaths, run_id: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    try:
        manifest = load_manifest(paths, run_id)
    except Exception as exc:
        return [ValidationIssue("error", f"manifest parse failed: {exc}")]

    if manifest.run_id != run_id:
        issues.append(ValidationIssue("error", f"run_id mismatch: {manifest.run_id} != {run_id}"))
    if not manifest.cycle_id:
        issues.append(ValidationIssue("error", "cycle_id is required"))
    if not manifest.direction_id:
        issues.append(ValidationIssue("error", "direction_id is required"))
    for field in ["entrypoint", "dryrun"]:
        command = (getattr(manifest, field) or {}).get("command", "")
        if not command:
            issues.append(ValidationIssue("error", f"{field}.command is required"))
            continue
        issues.extend(validate_command(command, field))
    for key in ["gpu", "cpus", "mem_gb", "time"]:
        if key not in manifest.resources:
            issues.append(ValidationIssue("warning", f"resources.{key} is missing"))
    return issues


def validate_command(command: str, label: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    try:
        argv = shlex.split(command)
    except ValueError as exc:
        return [ValidationIssue("error", f"{label}.command has invalid shell syntax: {exc}")]
    if not argv:
        return [ValidationIssue("error", f"{label}.command is empty")]
    if argv[0].split("/")[-1] in DANGEROUS_BINS:
        issues.append(ValidationIssue("error", f"{label}.command uses blocked executable: {argv[0]}"))
    if is_placeholder_command(command):
        issues.append(ValidationIssue("error", f"{label}.command is placeholder and cannot be scheduled"))
    return issues


def manifest_has_errors(paths: VibePaths, run_id: str) -> bool:
    return any(issue.level == "error" for issue in validate_manifest(paths, run_id))
