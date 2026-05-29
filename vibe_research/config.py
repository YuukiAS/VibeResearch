"""Config loading and migration helpers."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .io import read_json, read_yaml, utc_now, write_json, write_yaml
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


def load_config(paths: VibePaths) -> dict[str, Any]:
    default = ProjectConfig(project_name=paths.root.name).model_dump()
    json_config = read_json(paths.vibe / "config.json", {})
    yaml_config = read_yaml(paths.vibe / "config.yaml", {})
    return deep_merge(default, deep_merge(yaml_config if isinstance(yaml_config, dict) else {}, json_config if isinstance(json_config, dict) else {}))


def migrate_project(paths: VibePaths) -> dict[str, Any]:
    """Populate new config/state keys without deleting user edits."""

    config = load_config(paths)
    write_json(paths.vibe / "config.json", config)
    write_yaml(paths.vibe / "config.yaml", config)

    state = read_json(paths.state / "state.json", {})
    state = deep_merge(default_state(), state if isinstance(state, dict) else {})
    state["schema_version"] = 2
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    return config

