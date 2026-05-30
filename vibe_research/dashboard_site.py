"""Read-only static dashboard site generation and serving."""

from __future__ import annotations

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any

from .config import load_config
from .adapter_onboarding import adapter_readiness
from .ideas import read_ideas
from .io import ensure_dir, read_json, read_jsonl, write_text
from .papers import list_papers
from .paths import VibePaths
from .research_manager import budget_status, load_evidence, load_experiments, load_hypotheses, research_readiness
from .timeline import render_timeline_markdown


def build_dashboard_site(paths: VibePaths) -> Path:
    paths.require_initialized()
    ensure_dir(paths.site)
    data = dashboard_data(paths)
    write_text(paths.site / "dashboard.json", json.dumps(data, indent=2, sort_keys=True) + "\n")
    write_text(paths.site / "index.html", render_dashboard_html(data))
    return paths.site / "index.html"


def dashboard_data(paths: VibePaths) -> dict[str, Any]:
    state = read_json(paths.state / "state.json", {})
    return {
        "project": load_config(paths).get("project", {}),
        "status": read_json(paths.dashboard / "status.json", {}),
        "adapter_readiness": adapter_readiness(paths),
        "research_readiness": research_readiness(paths),
        "research_registry": {
            "hypotheses": load_hypotheses(paths),
            "experiments": load_experiments(paths),
            "evidence": load_evidence(paths),
            "budget": budget_status(paths),
        },
        "state": state,
        "timeline": read_jsonl(paths.dashboard / "timeline.jsonl"),
        "timeline_markdown": render_timeline_markdown(paths),
        "decisions": read_jsonl(paths.state / "decisions.jsonl"),
        "leaderboard": {
            "best": read_json(paths.leaderboard / "best.json", {}),
            "best_by_direction": read_json(paths.leaderboard / "best_by_direction.json", {}),
            "history": read_jsonl(paths.leaderboard / "history.jsonl"),
        },
        "cycles": load_artifact_dirs(paths.cycles, ["portfolio_plan.md", "portfolio_review.md", "resource_plan.yaml", "cycle_reflect.md", "cycle_revised_plan.md"]),
        "runs": load_artifact_dirs(paths.runs, ["proposal.md", "review.md", "manifest.yaml", "metrics.json", "reflect.md", "revised_plan.md", "launch.json"]),
        "ideas": read_ideas(paths),
        "deep_requests": read_jsonl(paths.research / "deep_requests" / "registry.jsonl"),
        "scheduler": {
            "queue": read_json(paths.scheduler / "queue.json", {"queued": []}),
            "active": read_json(paths.scheduler / "active_jobs.json", {"active": []}),
            "completed": read_jsonl(paths.scheduler / "completed_jobs.jsonl"),
            "budget": (paths.scheduler / "budget.yaml").read_text() if (paths.scheduler / "budget.yaml").exists() else "",
        },
        "papers": list_papers(paths),
        "wiki_pages": artifact_list(paths.research / "wiki"),
        "artifacts": artifact_list(paths.vibe),
        "meeting_reports": artifact_list(paths.reports / "meeting"),
        "codex_quota": "unknown/manual",
    }


def load_artifact_dirs(root: Path, names: list[str]) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    rows = []
    for item in sorted(path for path in root.iterdir() if path.is_dir()):
        artifacts = {}
        for name in names:
            path = item / name
            if path.exists():
                artifacts[name] = {"path": str(path), "text": path.read_text()[-6000:]}
        rows.append({"id": item.name, "artifacts": artifacts})
    return rows


def artifact_list(root: Path) -> list[str]:
    if not root.exists():
        return []
    return [str(path) for path in sorted(root.rglob("*")) if path.is_file()][:500]


def render_dashboard_html(data: dict[str, Any]) -> str:
    ideas = data["ideas"]
    deep_candidates = [row for row in ideas if row.get("status") == "needs_deep_research"]
    cycle_cards = "".join(card(row["id"], row["artifacts"].keys()) for row in data["cycles"]) or "<p>No cycles yet.</p>"
    run_cards = "".join(card(row["id"], row["artifacts"].keys()) for row in data["runs"]) or "<p>No runs yet.</p>"
    run_meta_rows = "".join(
        f"<tr><td><code>{esc(row.get('run_id',''))}</code></td><td>{esc(row.get('status',''))}</td><td>{esc(row.get('trust_status',''))}</td><td>{esc(row.get('schema_status',''))}</td><td>{esc((row.get('adapter_metadata') or {}).get('capability_id',''))}</td><td>{esc((row.get('adapter_metadata') or {}).get('adapter_revision',''))}</td></tr>"
        for row in data.get("status", {}).get("runs", [])
    ) or "<tr><td colspan='6'>No run metadata yet.</td></tr>"
    idea_rows = "".join(
        f"<tr><td><code>{esc(row.get('idea_id',''))}</code></td><td>{esc(row.get('status',''))}</td><td>{esc(row.get('priority',''))}</td><td>{esc(row.get('confidence',''))}</td><td>{esc(row.get('next_action',''))}</td><td>{esc(row.get('raw_text',''))}</td></tr>"
        for row in ideas
    ) or "<tr><td colspan='6'>No ideas yet.</td></tr>"
    deep_rows = "".join(
        f"<li><code>{esc(row.get('idea_id',''))}</code> <code>vibe deep-request-from-idea {esc(row.get('idea_id',''))}</code></li>" for row in deep_candidates
    ) or "<li>No deep research candidates.</li>"
    history_rows = "".join(
        f"<tr><td>{esc(row.get('run_id',''))}</td><td>{esc(row.get('direction_id',''))}</td><td>{esc(row.get('primary_metric',''))}</td><td>{esc(row.get('trusted',''))}</td><td>{esc(row.get('trust_status',''))}</td><td>{esc(row.get('schema_status',''))}</td></tr>"
        for row in data["leaderboard"]["history"][-20:]
    ) or "<tr><td colspan='6'>No leaderboard rows.</td></tr>"
    decision_rows = "".join(
        f"<tr><td><code>{esc(row.get('target_id',''))}</code></td><td>{esc(row.get('decision_type',''))}</td><td>{esc(row.get('confidence',''))}</td><td>{esc(row.get('rationale',''))}</td></tr>"
        for row in data["decisions"][-20:]
    ) or "<tr><td colspan='4'>No decisions yet.</td></tr>"
    timeline = "".join(f"<li><time>{esc(row.get('created_at',''))}</time> <strong>{esc(row.get('event',''))}</strong> {esc(row.get('summary',''))}</li>" for row in data["timeline"][-30:])
    readiness = data.get("adapter_readiness", {})
    readiness_rows = "".join(
        f"<tr><td>{esc(key)}</td><td>{esc(value)}</td></tr>"
        for key, value in [
            ("maturity", readiness.get("maturity_level", "missing")),
            ("revision", readiness.get("adapter_revision", "")),
            ("ready", readiness.get("ready_for_experiments", False)),
            ("active", ", ".join(readiness.get("active_capabilities", [])) or "none"),
            ("draft", ", ".join(readiness.get("draft_capabilities", [])) or "none"),
            ("blocked", ", ".join(readiness.get("blocked_capabilities", [])) or "none"),
            ("missing scripts", ", ".join(readiness.get("missing_scripts", [])) or "none"),
            ("missing metrics", ", ".join(readiness.get("missing_metrics_schemas", [])) or "none"),
            ("missing answers", len(readiness.get("missing_user_answers", []))),
            ("last lint", readiness.get("last_lint_status", "not_run")),
        ]
    )
    blocker_rows = "".join(f"<li>{esc(item)}</li>" for item in readiness.get("next_blockers", [])[:12]) or "<li>none</li>"
    research = data.get("research_readiness", {})
    registry = data.get("research_registry", {})
    research_rows = "".join(
        f"<tr><td>{esc(key)}</td><td>{esc(value)}</td></tr>"
        for key, value in [
            ("ready", research.get("ready_for_bounded_autonomy", False)),
            ("adapter ready", research.get("adapter_ready", False)),
            ("open questions", len(research.get("open_questions", []))),
            ("hypotheses", len(registry.get("hypotheses", {}))),
            ("experiments", len(registry.get("experiments", {}))),
            ("evidence", len(registry.get("evidence", {}))),
            ("remaining gpu-hours", registry.get("budget", {}).get("remaining_daily_gpu_hours", "")),
        ]
    )
    artifacts = "".join(f"<li><code>{esc(path)}</code></li>" for path in data["artifacts"][:80])
    meetings = "".join(f"<li><code>{esc(path)}</code></li>" for path in data["meeting_reports"]) or "<li>No meeting reports yet.</li>"
    papers = "".join(f"<li><code>{esc(row.get('paper_id',''))}</code> {esc(row.get('title',''))}</li>" for row in data["papers"][:30]) or "<li>No papers yet.</li>"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>VibeResearch Dashboard</title>
<style>
body {{ margin: 0; font-family: system-ui, -apple-system, Segoe UI, sans-serif; color: #20242a; background: #f7f8fa; }}
header {{ background: #ffffff; border-bottom: 1px solid #d9dee5; padding: 18px 24px; position: sticky; top: 0; }}
main {{ padding: 20px 24px 48px; display: grid; gap: 18px; }}
section {{ background: #ffffff; border: 1px solid #d9dee5; border-radius: 6px; padding: 16px; }}
h1 {{ font-size: 22px; margin: 0; }}
h2 {{ font-size: 16px; margin: 0 0 12px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }}
.card {{ border: 1px solid #e3e7ed; border-radius: 6px; padding: 12px; background: #fbfcfd; }}
table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
th, td {{ border-bottom: 1px solid #eef1f4; text-align: left; padding: 7px; vertical-align: top; }}
code {{ background: #eef1f4; border-radius: 4px; padding: 1px 4px; }}
ul {{ margin: 0; padding-left: 20px; }}
</style>
</head>
<body>
<header><h1>{esc(data.get('project', {}).get('name') or data.get('project', {}).get('project_name') or 'VibeResearch')}</h1><div>Codex quota: <code>{esc(data['codex_quota'])}</code></div></header>
<main>
<section><h2>Idea Intake</h2><p>Submit a prompt with <code>vibe idea "..."</code>. Dashboard actions are read-only by default.</p></section>
<section><h2>Adapter Readiness</h2><table><tr><th>Field</th><th>Value</th></tr>{readiness_rows}</table><h3>Next Blockers</h3><ul>{blocker_rows}</ul></section>
<section><h2>Research Manager</h2><table><tr><th>Field</th><th>Value</th></tr>{research_rows}</table></section>
<section><h2>Cycle Cards</h2><div class="grid">{cycle_cards}</div></section>
<section><h2>Run Cards</h2><div class="grid">{run_cards}</div></section>
<section><h2>Run Evidence And Adapter Metadata</h2><table><tr><th>Run</th><th>Status</th><th>Trust</th><th>Schema</th><th>Capability</th><th>Adapter Revision</th></tr>{run_meta_rows}</table></section>
<section><h2>Direction Board</h2><pre>{esc(json.dumps(data['leaderboard']['best_by_direction'], indent=2, sort_keys=True))}</pre></section>
<section><h2>Scheduler / Slurm Status</h2><pre>{esc(json.dumps(data['scheduler'], indent=2, sort_keys=True)[:8000])}</pre></section>
<section><h2>Decisions</h2><table><tr><th>Target</th><th>Decision</th><th>Confidence</th><th>Rationale</th></tr>{decision_rows}</table></section>
<section><h2>Leaderboard</h2><table><tr><th>Run</th><th>Direction</th><th>Metric</th><th>Trusted</th><th>Trust status</th><th>Schema</th></tr>{history_rows}</table></section>
<section><h2>Timeline</h2><ul>{timeline or '<li>No timeline events.</li>'}</ul></section>
<section><h2>Idea Pool</h2><table><tr><th>Idea</th><th>Status</th><th>Priority</th><th>Confidence</th><th>Next action</th><th>Text</th></tr>{idea_rows}</table></section>
<section><h2>Deep Research Decisions</h2><ul>{deep_rows}</ul></section>
<section><h2>Wiki / Paper Queue</h2><ul>{papers}</ul></section>
<section><h2>Artifact Browser</h2><ul>{artifacts}</ul></section>
<section><h2>Meeting Reports</h2><ul>{meetings}</ul></section>
</main>
</body>
</html>
"""


def card(title: str, artifact_names) -> str:
    items = "".join(f"<li><code>{esc(name)}</code></li>" for name in artifact_names)
    return f"<div class='card'><strong><code>{esc(title)}</code></strong><ul>{items}</ul></div>"


def esc(value: Any) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def serve_dashboard_site(paths: VibePaths, *, host: str = "127.0.0.1", port: int = 8765, once: bool = False) -> str:
    index = build_dashboard_site(paths)
    if once:
        return f"http://{host}:{port}/index.html -> {index}"

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(paths.site), **kwargs)

    server = ThreadingHTTPServer((host, port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()
    return f"http://{host}:{port}/index.html"
