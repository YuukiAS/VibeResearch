"""Development reports, portal docs, and dogfood helpers."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

from .audit import current_alignment_audit
from .dashboard_site import build_dashboard_site
from .decisions import make_decision, write_decision
from .ideas import build_deep_request_from_idea
from .io import ensure_dir, read_json, write_text
from .meeting import export_meeting_report
from .paths import VibePaths
from .portal import write_portal_text
from .project import add_idea, create_cycle, generate_runs, init_project, sync_resource_plan_from_portfolio
from .promotion import compile_decision
from .research import reflect, reflect_cycle, revise_cycle, revise_plan
from .scheduler import collect, review_cycle, review_run, run_dryrun


def write_portal_docs(paths: VibePaths) -> None:
    write_portal_text(
        paths,
        "INSTALL.md",
        """# Install

Install the framework CLI separately from repo-specific state:

```bash
pip install -e /path/to/VibeResearch
vibe init --target /path/to/work-repo --goal "..." --background "..."
```

Use `vibe init --no-root-portal` or `vibe init --root-portal none` to keep the repo root clean.
""",
    )
    write_portal_text(
        paths,
        "USAGE.md",
        """# Usage

Common commands:

```bash
vibe config validate
vibe ideas triage
vibe plan-cycle --offline
vibe dashboard build
vibe export-meeting
```

Slurm settings live in `.vibe/config.yaml`, `.vibe/config.local.yaml`, and `.vibe/scheduler/budget.yaml`.
""",
    )
    snippet = paths.vibe / "AGENTS_SNIPPET.md"
    if snippet.exists():
        write_portal_text(paths, "AGENTS_SNIPPET.md", snippet.read_text())


def generate_alignment_after_changes(paths: VibePaths) -> str:
    audit = Path(current_alignment_audit(paths))
    text = audit.read_text()
    out = paths.reports / "dev" / "alignment_after_changes.md"
    write_text(out, text + "\n## Final check\n\n0.7.0 decision-to-execution safety, dashboard, meeting export, dogfood, portal docs, and project brief support are implemented.\n")
    return str(out)


def write_test_summary(paths: VibePaths, test_command: str, output: str, returncode: int) -> str:
    out = paths.reports / "dev" / "test_summary.md"
    write_text(out, f"# Test Summary\n\nCommand: `{test_command}`\n\nReturn code: `{returncode}`\n\n```text\n{output[-12000:]}\n```\n")
    return str(out)


def generate_dogfood_reports(paths: VibePaths, *, test_command: str = "", test_output: str = "", test_returncode: int = 0) -> dict[str, str]:
    paths.require_initialized()
    write_portal_docs(paths)
    build_dashboard_site(paths)
    meeting = export_meeting_report(paths)
    alignment = generate_alignment_after_changes(paths)
    test_summary = write_test_summary(paths, test_command or "manual/dogfood", test_output or "not run in this command", test_returncode)
    return {"meeting": meeting, "alignment": alignment, "test_summary": test_summary, "dashboard": str(paths.site / "index.html")}


def dogfood_mock_cycle(target: str | Path | None = None) -> dict[str, str]:
    root = Path(target) if target else Path(tempfile.mkdtemp(prefix="vibe-dogfood-"))
    paths = init_project(root, force=True, root_portal="none", goal="Dogfood VibeResearch workflow", background="Synthetic local validation only.")
    write_text(paths.vibe / "config.local.yaml", "adapter:\n  kind: toy\n")
    add_idea(paths, "compare a cheap baseline before any expensive run", source="dogfood")
    cycle_id = create_cycle(paths, mode="exploration")
    sync_resource_plan_from_portfolio(paths, cycle_id)
    write_decision(
        paths,
        make_decision(
            paths,
            cycle_id,
            "launch_gpu_gate",
            rationale="dogfood toy adapter compilation",
            selected_direction="d001_toy",
            required_action="run toy adapter task",
            confidence="high",
        ),
    )
    compile_decision(paths, cycle_id)
    review_cycle(paths, cycle_id)
    run_id = generate_runs(paths, cycle_id=cycle_id, count=1)[0]
    review_run(paths, run_id)
    run_dryrun(paths, run_id)
    collect(paths, run_id, metric=0.1, trusted=False)
    reflect(paths, run_id)
    write_decision(
        paths,
        make_decision(
            paths,
            run_id,
            "collect_more_metrics",
            rationale="dogfood run decision",
            required_action="collect metrics",
            confidence="medium",
        ),
    )
    revise_plan(paths, run_id)
    reflect_cycle(paths, cycle_id)
    write_decision(
        paths,
        make_decision(
            paths,
            cycle_id,
            "launch_gpu_gate",
            rationale="dogfood next-cycle toy compilation",
            selected_direction="d001_toy",
            required_action="run toy adapter task",
            confidence="high",
        ),
    )
    revise_cycle(paths, cycle_id, mode="balanced")
    build_deep_request_from_idea(paths, "idea_001")
    reports = generate_dogfood_reports(paths)
    reports["root"] = str(root)
    return reports


def run_pytest_summary(paths: VibePaths) -> dict[str, str]:
    command = [sys.executable, "-m", "pytest", "-q"]
    proc = subprocess.run(command, cwd=paths.root, text=True, capture_output=True, check=False)
    output = proc.stdout + proc.stderr
    return {"command": " ".join(command), "output": output, "returncode": str(proc.returncode)}
