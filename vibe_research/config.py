"""Config loading and migration helpers."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import os
import shutil
import subprocess
import sys
from typing import Any

from pydantic import ValidationError

from .io import ensure_dir, read_json, read_yaml, utc_now, write_json, write_yaml
from .models import ProjectConfig, default_state
from .paths import VibePaths


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(paths: VibePaths, *, include_local: bool = True) -> dict[str, Any]:
    default = ProjectConfig(project_name=paths.root.name).model_dump()
    json_config = read_json(paths.vibe / "config.json", {})
    yaml_config = read_yaml(paths.vibe / "config.yaml", {})
    config = deep_merge(
        default,
        deep_merge(yaml_config if isinstance(yaml_config, dict) else {}, json_config if isinstance(json_config, dict) else {}),
    )
    if include_local:
        local_config = read_yaml(paths.vibe / "config.local.yaml", {})
        config = deep_merge(config, local_config if isinstance(local_config, dict) else {})
    return config


def config_schema() -> dict[str, Any]:
    return ProjectConfig.model_json_schema()


def write_config_schema(paths: VibePaths) -> None:
    write_json(paths.vibe / "config.schema.json", config_schema())


def validate_config(paths: VibePaths) -> list[str]:
    issues: list[str] = []
    config = load_config(paths, include_local=False)
    try:
        ProjectConfig.model_validate(config)
    except ValidationError as exc:
        issues.extend(f"{'.'.join(str(part) for part in err['loc'])}: {err['msg']}" for err in exc.errors())
    schema_path = paths.vibe / "config.schema.json"
    if not schema_path.exists():
        issues.append("missing .vibe/config.schema.json")
    else:
        try:
            read_json(schema_path, {})
        except Exception as exc:  # pragma: no cover - defensive parse reporting
            issues.append(f"invalid config.schema.json: {exc}")
    return issues


def migrate_project(paths: VibePaths) -> dict[str, Any]:
    """Populate new config/state keys without deleting user edits."""

    config = load_config(paths, include_local=False)
    write_json(paths.vibe / "config.json", config)
    write_yaml(paths.vibe / "config.yaml", config)
    if not (paths.vibe / "config.local.yaml").exists():
        write_yaml(paths.vibe / "config.local.yaml", {"local": {"notes": "local-only overrides; not auto-merged into config.yaml"}})
    write_config_schema(paths)

    state = read_json(paths.state / "state.json", {})
    state = deep_merge(default_state(), state if isinstance(state, dict) else {})
    state["schema_version"] = 3
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    return config


def command_probe(name: str, args: list[str] | None = None, *, cwd: Path | None = None, timeout: int = 5) -> dict[str, Any]:
    path = shutil.which(name)
    result: dict[str, Any] = {"path": path or "", "available": bool(path)}
    if not path:
        return result
    cmd = [path] + (args or [])
    try:
        completed = subprocess.run(cmd, cwd=str(cwd) if cwd else None, text=True, capture_output=True, timeout=timeout, check=False)
    except Exception as exc:
        result.update({"ok": False, "error": str(exc)})
        return result
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    result.update({"ok": completed.returncode == 0, "returncode": completed.returncode})
    if stdout:
        result["stdout"] = "\n".join(stdout.splitlines()[:20])
    if stderr:
        result["stderr"] = "\n".join(stderr.splitlines()[:20])
    return result


def detect_directories(root: Path) -> dict[str, list[str]]:
    data_names = ["data", "datasets", "input", "inputs"]
    result_names = ["results", "outputs", "artifacts", "runs"]
    return {
        "data": [str(root / name) for name in data_names if (root / name).exists()],
        "results": [str(root / name) for name in result_names if (root / name).exists()],
    }


def parse_gpu_names(output: str) -> list[str]:
    names = []
    for line in output.splitlines():
        text = line.strip()
        if text and not text.lower().startswith("name"):
            names.append(text)
    return names


def parse_sinfo_partitions(output: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in output.splitlines():
        text = line.strip()
        if not text:
            continue
        parts = text.split(None, 1)
        name = parts[0].replace("*", "").strip()
        gres_raw = parts[1].strip() if len(parts) > 1 else ""
        if not name:
            continue
        row: dict[str, Any] = {"name": name}
        if gres_raw and gres_raw.lower() not in {"(null)", "n/a", "none"}:
            row["gres_raw"] = gres_raw
            template = sinfo_gres_template(gres_raw)
            if template:
                row["gres"] = template
        rows.append(row)
    return rows


def sinfo_gres_template(gres_raw: str) -> str:
    first = gres_raw.split(",", 1)[0].strip()
    first = first.split("(", 1)[0].strip()
    if not first.startswith("gpu"):
        return ""
    parts = first.split(":")
    if len(parts) >= 3:
        return f"gpu:{parts[1]}:{{gpu}}"
    if len(parts) == 2 and not parts[1].isdigit():
        return f"gpu:{parts[1]}:{{gpu}}"
    return "gpu:{gpu}"


def detect_config(paths: VibePaths, *, write: bool = True) -> dict[str, Any]:
    git = command_probe("git", ["rev-parse", "--show-toplevel"], cwd=paths.root)
    repo_root = git.get("stdout") if git.get("ok") and git.get("stdout") else str(paths.root)
    commands = {
        name: command_probe(name, probe_args, cwd=paths.root)
        for name, probe_args in {
            "sinfo": ["-h", "-o", "%P %G"],
            "squeue": ["-h", "-o", "%.18i %.9P %.8j %.8u %.2t %.10M %.6D %R"],
            "sacct": ["-n", "-X", "-S", "now-1day", "-o", "JobID,State,Elapsed", "-P"],
            "sbatch": ["--version"],
            "scancel": ["--version"],
        }.items()
    }
    nvidia = command_probe("nvidia-smi", ["--query-gpu=name", "--format=csv,noheader"], cwd=paths.root)
    gpu_names = parse_gpu_names(str(nvidia.get("stdout", ""))) if nvidia.get("ok") else []
    sinfo_partitions = parse_sinfo_partitions(str(commands["sinfo"].get("stdout", ""))) if commands["sinfo"].get("ok") else []
    gres_by_partition = {row["name"]: row["gres"] for row in sinfo_partitions if row.get("gres")}
    detected = {
        "detected_at": utc_now(),
        "repo": {"root": str(repo_root), "vibe_root": str(paths.vibe)},
        "git": git,
        "python": {
            "executable": sys.executable,
            "version": sys.version.split()[0],
            "prefix": sys.prefix,
            "virtual_env": os.environ.get("VIRTUAL_ENV", ""),
        },
        "commands": commands,
        "slurm": {
            "available": any(commands[name].get("available") for name in ["sinfo", "squeue", "sacct", "sbatch"]),
            "sinfo": commands["sinfo"],
            "squeue": commands["squeue"],
            "sacct": commands["sacct"],
            "partitions": sinfo_partitions,
        },
        "gpu": {
            "nvidia_smi": nvidia,
            "count": len(gpu_names),
            "models": gpu_names,
        },
        "directories": detect_directories(paths.root),
        "suggested_config": {
            "execution": {
                "backend": "slurm" if any(commands[name].get("available") for name in ["sinfo", "squeue", "sbatch"]) else "local",
                "slurm": {
                    "partitions": sinfo_partitions,
                    "gres_by_partition": gres_by_partition,
                },
            },
            "slurm": {"enabled": any(commands[name].get("available") for name in ["sinfo", "squeue", "sbatch"])},
        },
    }
    if write:
        ensure_dir(paths.vibe)
        write_yaml(paths.vibe / "config.detected.yaml", detected)
    return detected
