"""Small IO helpers for the repo-local `.vibe` state layer."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text())


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def dump_simple_yaml(data: Any, indent: int = 0) -> str:
    """Dump a conservative YAML subset without requiring PyYAML.

    It supports the primitives this project writes: nested dicts, lists, bools,
    ints/floats, strings, and null. The output is intentionally simple so it is
    human-editable and easy to parse by PyYAML if users install it.
    """

    pad = " " * indent
    if isinstance(data, dict):
        lines: list[str] = []
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                lines.append(f"{pad}{key}:")
                lines.append(dump_simple_yaml(value, indent + 2))
            else:
                lines.append(f"{pad}{key}: {format_scalar(value)}")
        return "\n".join(lines)
    if isinstance(data, list):
        if not data:
            return f"{pad}[]"
        lines = []
        for item in data:
            if isinstance(item, (dict, list)):
                lines.append(f"{pad}-")
                lines.append(dump_simple_yaml(item, indent + 2))
            else:
                lines.append(f"{pad}- {format_scalar(item)}")
        return "\n".join(lines)
    return f"{pad}{format_scalar(data)}"


def format_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if not text:
        return '""'
    if any(ch in text for ch in [":", "#", "[", "]", "{", "}", "\n"]) or text.strip() != text:
        return json.dumps(text)
    return text


def write_yaml(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(dump_simple_yaml(data) + "\n")


def read_yaml(path: Path, default: Any) -> Any:
    """Read YAML when PyYAML exists, otherwise parse JSON or return default.

    The fallback keeps this CLI operational in minimal environments. It does not
    attempt to parse arbitrary YAML; generated state also has JSON mirrors where
    machine-read accuracy matters.
    """

    if not path.exists():
        return default
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(path.read_text())
        return default if loaded is None else loaded
    except Exception:
        text = path.read_text().strip()
        if text.startswith("{") or text.startswith("["):
            return json.loads(text)
        try:
            return parse_simple_yaml(text)
        except Exception:
            return default


def parse_simple_yaml(text: str) -> Any:
    """Parse the conservative YAML subset emitted by `dump_simple_yaml`."""

    lines = [(len(raw) - len(raw.lstrip(" ")), raw.lstrip(" ")) for raw in text.splitlines() if raw.strip()]
    if not lines:
        return None

    def parse_scalar(raw: str) -> Any:
        value = raw.strip()
        if value == "null":
            return None
        if value == "true":
            return True
        if value == "false":
            return False
        if value == "[]":
            return []
        if value.startswith('"') or value.startswith("[") or value.startswith("{"):
            return json.loads(value)
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            return value

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(lines):
            return {}, index
        is_list = lines[index][0] == indent and lines[index][1].startswith("-")
        if is_list:
            items = []
            while index < len(lines):
                current_indent, content = lines[index]
                if current_indent < indent:
                    break
                if current_indent != indent or not content.startswith("-"):
                    break
                rest = content[1:].strip()
                index += 1
                if rest:
                    items.append(parse_scalar(rest))
                else:
                    value, index = parse_block(index, indent + 2)
                    items.append(value)
            return items, index
        data: dict[str, Any] = {}
        while index < len(lines):
            current_indent, content = lines[index]
            if current_indent < indent:
                break
            if current_indent != indent or content.startswith("-"):
                break
            key, sep, rest = content.partition(":")
            if not sep:
                return parse_scalar(content), index + 1
            index += 1
            if rest.strip():
                data[key] = parse_scalar(rest.strip())
            else:
                value, index = parse_block(index, indent + 2)
                data[key] = value
        return data, index

    parsed, _ = parse_block(0, lines[0][0])
    return parsed


def write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    path.write_text(text)


def next_numeric_id(existing: Iterable[str], prefix: str) -> str:
    best = 0
    for item in existing:
        if item.startswith(prefix):
            digits = ""
            for ch in item[len(prefix) :]:
                if ch.isdigit():
                    digits += ch
                else:
                    break
            if digits:
                best = max(best, int(digits))
    return f"{prefix}{best + 1:03d}"


def slugify(text: str, max_len: int = 36) -> str:
    slug = []
    prev_dash = False
    for ch in text.lower():
        if ch.isalnum():
            slug.append(ch)
            prev_dash = False
        elif not prev_dash:
            slug.append("-")
            prev_dash = True
    value = "".join(slug).strip("-")
    return (value or "item")[:max_len].strip("-") or "item"
