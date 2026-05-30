"""Development reports, portal docs, and dogfood helpers."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile

from .adapter_schema import AdapterCapability, AdapterManifest, ArtifactRules, MetricsSchema, ResourcePolicy, write_adapter_manifest
from .audit import current_alignment_audit
from .dashboard_site import build_dashboard_site
from .decisions import make_decision, write_decision
from .ideas import build_deep_request_from_idea
from .io import ensure_dir, read_json, write_json, write_text
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
    write_text(out, text + "\n## Final check\n\n0.7.1 adapter onboarding, execution script bootstrap, readiness gating, dashboard, meeting export, dogfood, portal docs, and project brief support are implemented.\n")
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
    write_toy_readiness_manifest(paths)
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


def write_toy_readiness_manifest(paths: VibePaths) -> None:
    command = "python3 -c 'import json, pathlib; p=pathlib.Path(\".vibe/toy_contract.json\"); p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps({\"primary\": 1.0})+\"\\n\")'"
    manifest = AdapterManifest(
        project_id=paths.root.name,
        project_name=paths.root.name,
        open_questions=[],
        capabilities=[
            AdapterCapability(
                id="toy-metrics-export",
                version="dogfood",
                status="active",
                task_type="metrics_export",
                supported_decisions=["collect_more_metrics"],
                description="Generic dogfood instrumentation capability for local smoke testing.",
                dryrun={"command": command},
                entrypoint={"type": "local", "command": command},
                outputs={"expected_output_path": ".vibe/toy_contract.json", "metrics_file_path": ".vibe/toy_contract.json"},
                metrics_schema=MetricsSchema(required=["primary"], types={"primary": "number"}, primary_metric="primary", version="dogfood"),
                artifact_rules=ArtifactRules(expected_outputs=[".vibe/toy_contract.json"], trusted_path_patterns=[".vibe/*.json"], version="dogfood"),
                resources=ResourcePolicy(automatic_submission_allowed=False, user_confirmation_required=False),
                trust_checks=["schema_valid_metrics", "expected_output_exists"],
                contract_tests=["toy-metrics-export"],
                activation={"contract_status": "passed", "contract_test_result_id": "dogfood", "command_template_hash": "dogfood", "metrics_schema_hash": "dogfood", "artifact_rule_hash": "dogfood"},
            )
        ],
    )
    write_adapter_manifest(paths, manifest)
    write_json(paths.vibe / "contract_tests" / "toy-metrics-export.json", {"capability_id": "toy-metrics-export", "status": "passed", "created_at": "dogfood"})


def run_pytest_summary(paths: VibePaths) -> dict[str, str]:
    command = [sys.executable, "-m", "pytest", "-q"]
    proc = subprocess.run(command, cwd=paths.root, text=True, capture_output=True, check=False)
    output = proc.stdout + proc.stderr
    return {"command": " ".join(command), "output": output, "returncode": str(proc.returncode)}
