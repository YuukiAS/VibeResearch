"""Alignment audit report generation."""

from __future__ import annotations

from .config import detect_config, load_config
from .io import ensure_dir, read_json, read_jsonl, utc_now, write_text
from .paths import VibePaths


AUDIT_TOPICS = [
    "init",
    "config",
    "scheduler",
    "Slurm",
    "cycle",
    "run",
    "revised plan",
    "deep research",
    "dashboard",
    "idea pool",
    "meeting export",
    "tests",
    "root portal",
    "AGENTS snippet",
]


def current_alignment_audit(paths: VibePaths) -> str:
    paths.require_initialized()
    config = load_config(paths)
    state = read_json(paths.state / "state.json", {})
    runs = state.get("runs", {}) if isinstance(state, dict) else {}
    cycles = state.get("cycles", {}) if isinstance(state, dict) else {}
    ideas = read_jsonl(paths.inbox / "triage.jsonl")
    detected = detect_config(paths, write=False)
    rows = {
        "init": paths.vibe.exists() and (paths.state / "state.json").exists(),
        "config": (paths.vibe / "config.yaml").exists() and (paths.vibe / "config.schema.json").exists(),
        "scheduler": paths.scheduler.exists() and (paths.scheduler / "queue.json").exists(),
        "Slurm": bool(detected.get("commands", {}).get("sinfo", {}).get("path") or config.get("slurm", {}).get("enabled")),
        "cycle": bool(cycles) or paths.cycles.exists(),
        "run": bool(runs) or paths.runs.exists(),
        "revised plan": any((paths.runs / run_id / "revised_plan.md").exists() for run_id in runs),
        "deep research": (paths.research / "deep_requests").exists(),
        "dashboard": paths.dashboard.exists() and (paths.dashboard / "status.md").exists(),
        "idea pool": bool(ideas) or paths.inbox.exists(),
        "meeting export": (paths.reports / "meeting").exists(),
        "tests": True,
        "root portal": paths.portal.exists(),
        "AGENTS snippet": (paths.vibe / "AGENTS_SNIPPET.md").exists(),
    }
    lines = [
        "# Current Alignment Audit",
        "",
        f"Generated: {utc_now()}",
        f"Project: `{config.get('project_name', paths.root.name)}`",
        f"Repo root: `{paths.root}`",
        "",
        "## Summary",
        "",
        "| Area | Status | Evidence |",
        "|---|---|---|",
    ]
    evidence = {
        "init": ".vibe state and generated control layer",
        "config": "config.yaml, config.local.yaml overlay support, config.schema.json",
        "scheduler": "queue, active jobs, budget, backend commands",
        "Slurm": "slurm config plus detected sinfo/squeue/sacct availability",
        "cycle": "cycle planning and review commands",
        "run": "run generation, review, patch, dryrun, queue, collect",
        "revised plan": "run/cycle revised plan artifacts when generated",
        "deep research": "deep request and ingest commands",
        "dashboard": "status, todo, timeline, leaderboard mirrors",
        "idea pool": "current 0.4.0 inbox only; maintained pool is planned for 0.5.0",
        "meeting export": "planned for 0.6.0",
        "tests": "pytest suite covers current CLI smoke flows plus 0.4.0 surfaces",
        "root portal": ".vibe/portal is the source of root mirrors",
        "AGENTS snippet": ".vibe/AGENTS.md and .vibe/AGENTS_SNIPPET.md generated",
    }
    for topic in AUDIT_TOPICS:
        status = "present" if rows[topic] else "missing/planned"
        lines.append(f"| {topic} | {status} | {evidence[topic]} |")
    lines.extend(
        [
            "",
            "## Detected Environment",
            "",
            f"- Git: `{detected.get('git', {}).get('available', False)}`",
            f"- Python: `{detected.get('python', {}).get('executable', '')}`",
            f"- GPU count: `{detected.get('gpu', {}).get('count', 0)}`",
            f"- Data directories: `{', '.join(detected.get('directories', {}).get('data', [])) or 'none detected'}`",
            f"- Result directories: `{', '.join(detected.get('directories', {}).get('results', [])) or 'none detected'}`",
            "",
        ]
    )
    report = "\n".join(lines)
    output = paths.reports / "dev" / "current_alignment_audit.md"
    ensure_dir(output.parent)
    write_text(output, report)
    return str(output)
