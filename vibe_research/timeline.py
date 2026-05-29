"""Timeline event recording and rendering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .io import append_jsonl, read_jsonl, utc_now, write_text
from .models import TimelineEvent
from .paths import VibePaths


def record_event(
    paths: VibePaths,
    event: str,
    summary: str,
    *,
    cycle_id: str = "",
    run_id: str = "",
    direction_id: str = "",
    status: str = "",
    payload: dict[str, Any] | None = None,
) -> TimelineEvent:
    item = TimelineEvent(
        event=event,
        created_at=utc_now(),
        cycle_id=cycle_id,
        run_id=run_id,
        direction_id=direction_id,
        status=status,
        summary=summary,
        payload=payload or {},
    )
    append_jsonl(paths.dashboard / "timeline.jsonl", item.model_dump())
    return item


def load_timeline(paths: VibePaths) -> list[dict[str, Any]]:
    return read_jsonl(paths.dashboard / "timeline.jsonl")


def render_timeline_markdown(paths: VibePaths) -> str:
    rows = load_timeline(paths)
    lines = ["# Vibe Timeline", ""]
    if not rows:
        lines.append("No events recorded yet.")
    for row in rows[-200:]:
        ids = " ".join(
            part
            for part in [
                row.get("cycle_id", ""),
                row.get("run_id", ""),
                row.get("direction_id", ""),
            ]
            if part
        )
        suffix = f" | {ids}" if ids else ""
        status = f" [{row.get('status')}]" if row.get("status") else ""
        lines.append(f"- {row['created_at']} `{row['event']}`{status}{suffix}: {row.get('summary', '')}")
    return "\n".join(lines) + "\n"


def render_timeline_html(paths: VibePaths) -> str:
    rows = load_timeline(paths)[-200:]
    items = "\n".join(
        f"<li><time>{escape(row['created_at'])}</time> "
        f"<strong>{escape(row['event'])}</strong> "
        f"<span>{escape(row.get('cycle_id', ''))} {escape(row.get('run_id', ''))}</span>"
        f"<p>{escape(row.get('summary', ''))}</p></li>"
        for row in rows
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Vibe Timeline</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 32px; color: #172026; }}
h1 {{ font-size: 24px; }}
ol {{ border-left: 2px solid #9aa7b2; padding-left: 24px; }}
li {{ margin: 0 0 18px; padding-left: 8px; }}
time {{ color: #61707d; font-size: 12px; display: block; }}
strong {{ font-size: 14px; }}
span {{ color: #61707d; margin-left: 8px; }}
p {{ margin: 4px 0 0; }}
</style>
</head>
<body><h1>Vibe Timeline</h1><ol>{items}</ol></body></html>
"""


def render_timeline_svg(paths: VibePaths) -> str:
    rows = load_timeline(paths)[-40:]
    height = max(120, 34 * len(rows) + 40)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" viewBox="0 0 1200 {height}">',
        '<rect width="1200" height="100%" fill="#f8fafc"/>',
        '<text x="24" y="28" font-family="Arial" font-size="20" font-weight="700" fill="#172026">Vibe Timeline</text>',
        '<line x1="34" y1="50" x2="34" y2="' + str(height - 20) + '" stroke="#8aa0b4" stroke-width="2"/>',
    ]
    y = 64
    for row in rows:
        label = f"{row['created_at']} {row['event']} {row.get('cycle_id', '')} {row.get('run_id', '')}"
        parts.append(f'<circle cx="34" cy="{y - 4}" r="5" fill="#2563eb"/>')
        parts.append(
            f'<text x="52" y="{y}" font-family="Arial" font-size="13" fill="#172026">{escape(label)}: {escape(row.get("summary", ""))}</text>'
        )
        y += 34
    parts.append("</svg>")
    return "\n".join(parts)


def sync_timeline_files(paths: VibePaths) -> None:
    markdown = render_timeline_markdown(paths)
    write_text(paths.dashboard / "TIMELINE.md", markdown)
    write_text(paths.root / "VIBE_TIMELINE.md", markdown)
    write_text(paths.dashboard / "timeline.html", render_timeline_html(paths))
    write_text(paths.dashboard / "timeline.svg", render_timeline_svg(paths))


def escape(text: Any) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )

