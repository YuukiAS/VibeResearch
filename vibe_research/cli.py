"""Command line interface for VibeResearch."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .adapter_onboarding import (
    activate_capability,
    adapter_discover,
    adapter_doctor,
    adapter_draft,
    adapter_init,
    adapter_lint,
    adapter_questions,
    run_contract_test,
    script_bootstrap,
    write_real_experiment_gap_report,
)
from .artifacts import validate_artifact, validate_hard_rules
from .audit import current_alignment_audit
from .automation import auto_cycle as run_auto_cycle
from .automation import auto_next as run_auto_next
from .automation import scheduler_explain as render_scheduler_explain
from .bootstrap import (
    archive_legacy,
    bootstrap_init,
    bootstrap_resume,
    bootstrap_run,
    bootstrap_status,
    build_readiness,
    create_local_dogfood_profile,
    export_readiness_dashboard,
    import_legacy,
    run_dogfood,
)
from .codex_adapter import artifact_path, prompt_packet, run_codex
from .config import detect_config, load_config, migrate_project, validate_config
from .daemon import daemon_start, daemon_status, daemon_stop
from .dashboard import render_leaderboard, render_status, sync_dashboard
from .dashboard_site import build_dashboard_site, serve_dashboard_site
from .decisions import decision_json, make_decision, validate_decision_file, write_block_decision, write_decision
from .directions import set_direction_status
from .git_ops import abandon_run, create_branch, git_available, git_current_branch, git_diff_text, merge_review, merge_run, protected_diff_paths
from .ideas import archive_idea as archive_pool_idea
from .ideas import build_deep_request_from_idea
from .ideas import clean_ideas, get_idea, promote_idea, read_ideas, reject_idea, triage_ideas
from .io import read_json, read_jsonl, read_yaml
from .manifest import validate_manifest
from .meeting import export_meeting_report
from .next_action import compute_next_action
from .papers import add_paper, download_paper, list_papers, paper_search, pdf_to_markdown, wiki_ingest_paper
from .paths import VibePaths
from .portal import build_portal
from .project import add_directive, add_idea, create_cycle, generate_runs, init_project, sync_resource_plan_from_portfolio, vendor_runtime
from .promotion import compile_decision as compile_cycle_decision
from .promotion import validate_resource_plan
from .research import deep_request, ingest_deep_research, literature_refresh, reflect, reflect_cycle, revise_cycle, revise_plan
from .reports import generate_alignment_after_changes, generate_dogfood_reports, write_portal_docs
from .research_manager import (
    add_evidence,
    audit_registry,
    budget_status as research_budget_status,
    build_memory_pack,
    change_hypothesis_status,
    create_experiment as research_create_experiment,
    create_hypothesis,
    export_research_dashboard,
    link_run_to_experiment,
    load_experiments,
    load_hypotheses,
    policy_lint,
    portfolio_audit as research_portfolio_audit,
    portfolio_plan as research_portfolio_plan,
    portfolio_schedule as research_portfolio_schedule,
    reconcile_budget,
    render_daily_memo,
    reserve_budget,
    research_init,
)
from .real_experiments import summarize_real_experiment_progress
from .scheduler import collect as collect_run
from .scheduler import cancel_run, monitor as monitor_jobs
from .scheduler import queue_run, review_cycle, review_run, run_dryrun, submit_queue
from .timeline import render_timeline_markdown, sync_timeline_files

app = typer.Typer(help="Repo-specific sustained Vibe Research orchestration.")
daemon_app = typer.Typer(help="Manage tmux-backed VibeResearch daemon.")
config_app = typer.Typer(help="Inspect, validate, detect, and edit VibeResearch config.")
portal_app = typer.Typer(help="Build root portal mirrors from .vibe/portal.")
audit_app = typer.Typer(help="Generate alignment audit reports.")
ideas_app = typer.Typer(help="Manage the maintained research idea pool.")
dashboard_app = typer.Typer(help="Build and serve the read-only static dashboard.")
decision_app = typer.Typer(help="Inspect and write structured research decisions.")
adapter_app = typer.Typer(help="Manage adapter onboarding, readiness, and capability activation.")
script_app = typer.Typer(help="Bootstrap downstream execution wrapper scripts.")
bootstrap_app = typer.Typer(help="Run resumable project bootstrap, readiness, archive, and dogfood workflows.")
research_app = typer.Typer(help="Initialize and audit bounded autonomous research state.")
hypothesis_app = typer.Typer(help="Manage hypothesis registry records.")
experiment_app = typer.Typer(help="Manage experiment registry and evidence links.")
memory_app = typer.Typer(help="Build multi-cycle research memory packs.")
portfolio_app = typer.Typer(help="Plan, schedule, and audit bounded experiment portfolios.")
policy_app = typer.Typer(help="Inspect and lint research policies.")
budget_app = typer.Typer(help="Reserve, reconcile, and inspect research budget.")
memo_app = typer.Typer(help="Generate daily research memos.")
app.add_typer(daemon_app, name="daemon")
app.add_typer(config_app, name="config")
app.add_typer(portal_app, name="portal")
app.add_typer(audit_app, name="audit")
app.add_typer(ideas_app, name="ideas")
app.add_typer(dashboard_app, name="dashboard")
app.add_typer(decision_app, name="decision")
app.add_typer(adapter_app, name="adapter")
app.add_typer(script_app, name="script")
app.add_typer(bootstrap_app, name="bootstrap")
app.add_typer(research_app, name="research")
app.add_typer(hypothesis_app, name="hypothesis")
app.add_typer(experiment_app, name="experiment")
app.add_typer(memory_app, name="memory")
app.add_typer(portfolio_app, name="portfolio")
app.add_typer(policy_app, name="policy")
app.add_typer(budget_app, name="budget")
app.add_typer(memo_app, name="memo")
console = Console()


def paths(target: Path) -> VibePaths:
    return VibePaths(target)


@app.command()
def init(
    target: Path = typer.Option(Path("."), "--target", "-t", help="Target repository to initialize."),
    project_name: Optional[str] = typer.Option(None, "--project-name"),
    force: bool = typer.Option(False, "--force", help="Rewrite generated Vibe files."),
    auto: bool = typer.Option(False, "--auto", help="Use non-interactive defaults."),
    minimal: bool = typer.Option(False, "--minimal", help="Initialize only the local control layer."),
    root_portal: str = typer.Option("copy", "--root-portal", help="Root mirror mode: copy, symlink, or none."),
    no_root_portal: bool = typer.Option(False, "--no-root-portal", help="Do not create root mirror files."),
    install_agents_snippet: bool = typer.Option(False, "--install-agents-snippet", help="Append the generated snippet to root AGENTS.md."),
    goal: str = typer.Option("", "--goal", help="Project research goal."),
    background: str = typer.Option("", "--background", help="Project background and constraints."),
    brief_file: Optional[Path] = typer.Option(None, "--brief-file", help="Markdown file to import as .vibe/project/brief.md."),
    idea: list[str] = typer.Option([], "--idea", help="Initial idea; may be repeated."),
    idea_file: Optional[Path] = typer.Option(None, "--idea-file", help="File containing initial ideas, one per line."),
) -> None:
    """Initialize `.vibe/` and root progress files in a target repo."""

    if not auto and not minimal and not brief_file and not goal and sys.stdin.isatty():
        goal = typer.prompt("Project goal")
    if not auto and not minimal and not brief_file and not background and sys.stdin.isatty():
        background = typer.prompt("Project background")
    selected_portal = "none" if no_root_portal else root_portal
    if selected_portal not in {"copy", "symlink", "none"}:
        raise typer.BadParameter("--root-portal must be copy, symlink, or none")
    p = init_project(
        target,
        project_name=project_name,
        force=force,
        minimal=minimal,
        root_portal=selected_portal,
        install_agents=install_agents_snippet,
        goal=goal,
        background=background,
        brief_file=brief_file,
        initial_ideas=idea,
        idea_file=idea_file,
    )
    console.print(f"Initialized VibeResearch at [bold]{p.root}[/bold]")


@app.command("vendor-runtime")
def vendor_runtime_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Write a repo-local runtime scaffold under .vibe/runtime."""

    path = vendor_runtime(paths(target))
    console.print(f"Vendored runtime scaffold at {path}")


@adapter_app.command("init")
def adapter_init_cmd(target: Path = typer.Option(Path("."), "--target", "-t"), minimal: bool = typer.Option(False, "--minimal")) -> None:
    """Create adapter onboarding files without activating capabilities."""

    p = paths(target)
    if not p.vibe.exists():
        init_project(target, minimal=True, root_portal="none")
    result = adapter_init(p, minimal=minimal)
    sync_dashboard(p)
    console.print_json(data=result)


@adapter_app.command("discover")
def adapter_discover_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Scan a downstream repo for candidate scripts, metrics, configs, and risks."""

    p = paths(target)
    result = adapter_discover(p)
    sync_dashboard(p)
    console.print_json(data=result)


@adapter_app.command("draft")
def adapter_draft_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Update draft adapter capabilities and blocker questions from discovery."""

    p = paths(target)
    manifest = adapter_draft(p)
    sync_dashboard(p)
    console.print(f"Drafted adapter {manifest.adapter_revision}")


@adapter_app.command("ask")
def adapter_ask_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    question_id: Optional[str] = typer.Option(None, "--id"),
    answer: Optional[str] = typer.Option(None, "--answer"),
    confirm: bool = typer.Option(False, "--confirm"),
) -> None:
    """Show or update adapter questions."""

    update = (question_id, answer) if question_id and answer is not None else None
    p = paths(target)
    rows = adapter_questions(p, answer=update, confirm=confirm)
    sync_dashboard(p)
    console.print_json(data={"questions": rows})


@adapter_app.command("lint")
def adapter_lint_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Lint adapter manifest and write .vibe/adapter_lint.json."""

    p = paths(target)
    result = adapter_lint(p)
    sync_dashboard(p)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@adapter_app.command("doctor")
def adapter_doctor_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Write and print adapter readiness diagnostics."""

    p = paths(target)
    result = adapter_doctor(p)
    sync_dashboard(p)
    console.print_json(data=result)


@adapter_app.command("real-gaps")
def adapter_real_gaps_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Write and print missing contracts for backend-submitted real experiments."""

    p = paths(target)
    readiness = adapter_doctor(p)
    report = write_real_experiment_gap_report(p, readiness)
    sync_dashboard(p)
    console.print_json(data=report)


@adapter_app.command("contract-test")
def adapter_contract_test_cmd(capability_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Run lightweight contract tests for one capability."""

    p = paths(target)
    result = run_contract_test(p, capability_id)
    sync_dashboard(p)
    console.print_json(data=result)
    if result.get("status") != "passed":
        raise typer.Exit(1)


@adapter_app.command("activate")
def adapter_activate_cmd(
    capability_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    confirm: str = typer.Option("", "--confirm"),
) -> None:
    """Activate a linted and contract-tested capability."""

    p = paths(target)
    result = activate_capability(p, capability_id, user_confirmation=confirm)
    adapter_lint(p)
    adapter_doctor(p)
    sync_dashboard(p)
    console.print_json(data=result)


@script_app.command("bootstrap")
def script_bootstrap_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    plan: bool = typer.Option(False, "--plan", help="Only write the bootstrap plan; do not generate wrappers."),
    script_dir: str = typer.Option(".vibe/scripts", "--script-dir"),
) -> None:
    """Write a script bootstrap plan and optional draft wrappers."""

    p = paths(target)
    path = script_bootstrap(p, generate=not plan, script_dir=script_dir)
    sync_dashboard(p)
    console.print(str(path))


@bootstrap_app.command("init")
def bootstrap_init_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    goal: str = typer.Option("", "--goal"),
    background: str = typer.Option("", "--background"),
    memo_language: str = typer.Option("zh-CN", "--memo-language"),
    autonomy_level: str = typer.Option("analysis_only", "--autonomy-level"),
    mode: str = typer.Option("fresh", "--mode"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Create or refresh bootstrap session state."""

    p = paths(target)
    if not p.vibe.exists():
        init_project(target, goal=goal, background=background, root_portal="none")
    state = bootstrap_init(p, mode=mode, goal=goal, background=background, memo_language=memo_language, autonomy_level=autonomy_level, force=force)
    console.print_json(data={"session_id": state["session_id"], "state": str(p.vibe / "bootstrap" / "state.json")})


@bootstrap_app.command("run")
def bootstrap_run_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    start_phase: Optional[str] = typer.Option(None, "--start-phase"),
    stop_after: Optional[str] = typer.Option(None, "--stop-after"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Run ordered bootstrap phases until complete or blocked."""

    p = paths(target)
    state = bootstrap_run(p, start_phase=start_phase, stop_after=stop_after, non_interactive=True, force=force)
    sync_dashboard(p)
    console.print_json(data={"session_id": state.get("session_id"), "current_phase": state.get("current_phase"), "readiness_level": state.get("readiness_level"), "blocked_phases": state.get("blocked_phases", [])})


@bootstrap_app.command("resume")
def bootstrap_resume_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Resume from the latest blocked or failed bootstrap phase without overwriting user edits."""

    p = paths(target)
    state = bootstrap_resume(p, non_interactive=True)
    sync_dashboard(p)
    console.print_json(data={"session_id": state.get("session_id"), "current_phase": state.get("current_phase"), "blocked_phases": state.get("blocked_phases", []), "merge_warnings": state.get("merge_warnings", [])})


@bootstrap_app.command("status")
def bootstrap_status_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Print bootstrap state and readiness summary."""

    console.print_json(data=bootstrap_status(paths(target)))


@bootstrap_app.command("doctor")
def bootstrap_doctor_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Regenerate bootstrap readiness report and dashboard-ready readiness export."""

    p = paths(target)
    readiness = build_readiness(p)
    from .io import write_json, write_text
    from .bootstrap import bootstrap_dir, render_readiness_report

    write_json(bootstrap_dir(p) / "readiness.json", readiness)
    write_text(bootstrap_dir(p) / "readiness_report.md", render_readiness_report(readiness))
    export_readiness_dashboard(p)
    sync_dashboard(p)
    console.print_json(data={"readiness_level": readiness["readiness_level"], "report": str(p.vibe / "bootstrap" / "readiness_report.md")})


@bootstrap_app.command("archive")
def bootstrap_archive_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    source: Optional[Path] = typer.Option(None, "--source"),
    note: str = typer.Option("", "--note"),
) -> None:
    """Archive old VibeResearch/downstream automation state as untrusted regression evidence."""

    result = archive_legacy(paths(target), source=source, note=note)
    console.print_json(data={"archive_id": result["archive_id"], "file_count": result["file_count"], "manifest": str(paths(target).vibe / "archives" / result["archive_id"] / "manifest.json")})


@bootstrap_app.command("import-legacy")
def bootstrap_import_legacy_cmd(archive_manifest: Path, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Import archive summaries as imported_unverified historical context."""

    console.print_json(data=import_legacy(paths(target), archive_manifest))


@bootstrap_app.command("dogfood")
def bootstrap_dogfood_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    profile: str = typer.Option("0.8.3-happy-path", "--profile"),
    external_repo: Optional[Path] = typer.Option(None, "--external-repo"),
    brief_file: Optional[Path] = typer.Option(None, "--brief-file"),
    output_report: Optional[Path] = typer.Option(None, "--output-report"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Run local ignored sandbox or external-repo bootstrap dogfood."""

    p = paths(target)
    if not p.vibe.exists():
        init_project(target, minimal=True, root_portal="none")
    result = run_dogfood(p, profile=profile, external_repo=external_repo, brief_file=brief_file, output_report=output_report, dry_run=dry_run)
    console.print_json(data={"profile": result["profile"], "repo": result["repo"], "issues": result["issues"], "report": str(output_report or (p.vibe / "bootstrap" / "dogfood_report.json"))})


@bootstrap_app.command("sandbox")
def bootstrap_sandbox_cmd(target: Path = typer.Option(Path("."), "--target", "-t"), profile: str = typer.Option("0.8.3-happy-path", "--profile")) -> None:
    """Create one ignored local `.vibe_dogfood/` profile without running bootstrap."""

    path = create_local_dogfood_profile(paths(target).root, profile)
    console.print(str(path))


@research_app.command("init")
def research_init_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    goal: str = typer.Option("", "--goal"),
    background: str = typer.Option("", "--background"),
    memo_language: str = typer.Option("zh-CN", "--memo-language"),
    timezone: str = typer.Option("local", "--timezone"),
    autonomy_level: str = typer.Option("analysis_only", "--autonomy-level"),
    force: bool = typer.Option(False, "--force", help="Rewrite generated policy defaults and record policy history."),
) -> None:
    """Initialize research registry, policy files, blocker questions, and memo config."""

    p = paths(target)
    result = research_init(p, goal=goal, background=background, memo_language=memo_language, timezone=timezone, autonomy_level=autonomy_level, force=force)
    sync_dashboard(p)
    console.print_json(data=result)


@research_app.command("audit")
def research_audit_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Audit research registry integrity and duplicate-risk state."""

    result = audit_registry(paths(target))
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@hypothesis_app.command("create")
def hypothesis_create_cmd(
    title: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    rationale: str = typer.Option("", "--rationale"),
    stage: str = typer.Option("idea", "--stage"),
    target_metric: list[str] = typer.Option([], "--target-metric"),
) -> None:
    """Create a hypothesis registry record."""

    row = create_hypothesis(paths(target), title, rationale=rationale, stage=stage, target_metrics=target_metric)
    sync_dashboard(paths(target))
    console.print_json(data=row)


@hypothesis_app.command("list")
def hypothesis_list_cmd(target: Path = typer.Option(Path("."), "--target", "-t"), status: Optional[str] = typer.Option(None, "--status")) -> None:
    """List hypothesis registry records."""

    table = Table(title="Hypotheses")
    for col in ["Hypothesis", "Status", "Stage", "Title", "Next change"]:
        table.add_column(col)
    for row in load_hypotheses(paths(target)).values():
        if status and row.get("status") != status:
            continue
        table.add_row(row.get("hypothesis_id", ""), row.get("status", ""), row.get("current_stage", row.get("stage", "")), row.get("title", ""), row.get("next_testable_change", ""))
    console.print(table)


@hypothesis_app.command("show")
def hypothesis_show_cmd(hypothesis_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Print one hypothesis registry record."""

    row = load_hypotheses(paths(target)).get(hypothesis_id)
    if not row:
        raise typer.BadParameter(f"Unknown hypothesis: {hypothesis_id}")
    console.print_json(data=row)


@hypothesis_app.command("update")
def hypothesis_update_cmd(
    hypothesis_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    status: Optional[str] = typer.Option(None, "--status"),
    stage: Optional[str] = typer.Option(None, "--stage"),
    next_testable_change: Optional[str] = typer.Option(None, "--next-testable-change"),
    failure_analysis: Optional[str] = typer.Option(None, "--failure-analysis"),
) -> None:
    """Update mutable hypothesis fields."""

    from .research_manager import update_hypothesis

    updates = {
        "status": status,
        "stage": stage,
        "current_stage": stage,
        "next_testable_change": next_testable_change,
        "failure_analysis": {"summary": failure_analysis} if failure_analysis else None,
    }
    row = update_hypothesis(paths(target), hypothesis_id, updates)
    sync_dashboard(paths(target))
    console.print_json(data=row)


@hypothesis_app.command("stop")
def hypothesis_stop_cmd(
    hypothesis_id: str,
    reason: str = typer.Option(..., "--reason"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    user_decision: bool = typer.Option(False, "--user-decision"),
) -> None:
    """Stop a hypothesis when trusted negative evidence or user decision exists."""

    try:
        row = change_hypothesis_status(paths(target), hypothesis_id, "stop", reason=reason, user_decision=user_decision)
    except RuntimeError as exc:
        console.print(f"[error] {exc}")
        raise typer.Exit(1) from exc
    sync_dashboard(paths(target))
    console.print_json(data=row)


@hypothesis_app.command("promote")
def hypothesis_promote_cmd(hypothesis_id: str, reason: str = typer.Option(..., "--reason"), target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Promote a hypothesis only with trusted schema-valid evidence and no protected regression."""

    try:
        row = change_hypothesis_status(paths(target), hypothesis_id, "promote", reason=reason)
    except RuntimeError as exc:
        console.print(f"[error] {exc}")
        raise typer.Exit(1) from exc
    sync_dashboard(paths(target))
    console.print_json(data=row)


@hypothesis_app.command("downscope")
def hypothesis_downscope_cmd(
    hypothesis_id: str,
    reason: str = typer.Option(..., "--reason"),
    next_testable_change: str = typer.Option("", "--next-testable-change"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Downscope a hypothesis while preserving its evidence history."""

    row = change_hypothesis_status(paths(target), hypothesis_id, "downscope", reason=reason, remaining_upside={"next_testable_change": next_testable_change})
    sync_dashboard(paths(target))
    console.print_json(data=row)


@experiment_app.command("create")
def experiment_create_cmd(
    hypothesis_id: str,
    design_summary: str = typer.Option(..., "--design"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    stage: str = typer.Option("smoke", "--stage"),
    capability_id: str = typer.Option("", "--capability"),
    baseline_target: str = typer.Option("", "--baseline"),
) -> None:
    """Create an experiment linked to a hypothesis."""

    row = research_create_experiment(paths(target), hypothesis_id, design_summary, stage=stage, capability_id=capability_id, baseline_target=baseline_target)
    sync_dashboard(paths(target))
    console.print_json(data=row)


@experiment_app.command("link-run")
def experiment_link_run_cmd(experiment_id: str, run_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Link an engineering run to a research experiment."""

    row = link_run_to_experiment(paths(target), experiment_id, run_id)
    sync_dashboard(paths(target))
    console.print_json(data=row)


@experiment_app.command("analyze")
def experiment_analyze_cmd(
    experiment_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    run_id: str = typer.Option("", "--run-id"),
    trusted: bool = typer.Option(False, "--trusted"),
    schema_valid: bool = typer.Option(False, "--schema-valid"),
    summary: str = typer.Option("", "--summary"),
    metrics_file: str = typer.Option("", "--metrics-file"),
    primary_delta: float = typer.Option(0.0, "--primary-delta"),
    failure_kind: str = typer.Option("none", "--failure-kind"),
    protected_regression: bool = typer.Option(False, "--protected-regression"),
) -> None:
    """Record trusted or untrusted evidence and structured failure analysis."""

    regressions = [{"metric": "protected", "delta": "regressed"}] if protected_regression else []
    row = add_evidence(paths(target), experiment_id, run_id=run_id, trusted=trusted, schema_valid=schema_valid, summary=summary, metrics_file=metrics_file, metric_deltas={"primary": primary_delta}, protected_metric_regressions=regressions, failure_kind=failure_kind)
    sync_dashboard(paths(target))
    console.print_json(data=row)


@experiment_app.command("show")
def experiment_show_cmd(experiment_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Print one experiment record."""

    row = load_experiments(paths(target)).get(experiment_id)
    if not row:
        raise typer.BadParameter(f"Unknown experiment: {experiment_id}")
    console.print_json(data=row)


@experiment_app.command("real-progress")
def experiment_real_progress_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Print backend-submitted real-experiment progress accounting."""

    console.print_json(data=summarize_real_experiment_progress(paths(target), write=True))


@memory_app.command("build")
def memory_build_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Build a multi-cycle memory pack from registry and policy state."""

    pack = build_memory_pack(paths(target))
    console.print_json(data={"path": str(paths(target).research / "memory_pack.json"), "active_hypotheses": len(pack["active_hypotheses"]), "duplicate_risk_warnings": len(pack["duplicate_risk_warnings"])})


@portfolio_app.command("plan")
def portfolio_plan_cmd(target: Path = typer.Option(Path("."), "--target", "-t"), candidate_file: Optional[Path] = typer.Option(None, "--candidate-file")) -> None:
    """Evaluate agent-proposed candidate experiments under capability, policy, and budget constraints."""

    candidates = read_json(candidate_file, []) if candidate_file else None
    result = research_portfolio_plan(paths(target), candidates=candidates)
    console.print_json(data=result)


@portfolio_app.command("schedule")
def portfolio_schedule_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Reserve budget and create experiment records for selected portfolio candidates."""

    result = research_portfolio_schedule(paths(target))
    sync_dashboard(paths(target))
    console.print_json(data=result)


@portfolio_app.command("audit")
def portfolio_audit_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Audit portfolio selections against current capabilities and duplicate risks."""

    result = research_portfolio_audit(paths(target))
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@policy_app.command("lint")
def policy_lint_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Lint budget, stage-gate, and autonomy policies."""

    result = policy_lint(paths(target))
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@policy_app.command("show")
def policy_show_cmd(policy: str = typer.Argument("all"), target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Print one policy or all research policies."""

    p = paths(target)
    data = {
        "budget": read_yaml(p.vibe / "policies" / "budget.yaml", {}),
        "stage_gates": read_yaml(p.vibe / "policies" / "stage_gates.yaml", {}),
        "autonomy": read_yaml(p.vibe / "policies" / "autonomy.yaml", {}),
        "memo": read_yaml(p.research / "memo_config.yaml", {}),
    }
    console.print_json(data=data if policy == "all" else data.get(policy, {}))


@budget_app.command("status")
def budget_status_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Show budget reservations, spend, and remaining caps."""

    console.print_json(data=research_budget_status(paths(target)))


@budget_app.command("reserve")
def budget_reserve_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    hypothesis_id: str = typer.Option("", "--hypothesis-id"),
    experiment_id: str = typer.Option("", "--experiment-id"),
    decision_id: str = typer.Option("", "--decision-id"),
    gpu_hours: Optional[float] = typer.Option(None, "--gpu-hours"),
    confirmed: bool = typer.Option(False, "--confirmed"),
) -> None:
    """Reserve budget before queueing or scheduling a research action."""

    units = {"gpu_hours": gpu_hours} if gpu_hours is not None else {}
    row = reserve_budget(paths(target), decision_id=decision_id, experiment_id=experiment_id, hypothesis_id=hypothesis_id, resource_units=units, confirmed=confirmed)
    console.print_json(data=row)
    if row.get("status") == "blocked":
        raise typer.Exit(1)


@budget_app.command("reconcile")
def budget_reconcile_cmd(budget_event_id: str, target: Path = typer.Option(Path("."), "--target", "-t"), gpu_hours: float = typer.Option(0.0, "--gpu-hours")) -> None:
    """Reconcile actual resource usage after completion."""

    console.print_json(data=reconcile_budget(paths(target), budget_event_id, {"gpu_hours": gpu_hours}))


@memo_app.command("daily")
def memo_daily_cmd(target: Path = typer.Option(Path("."), "--target", "-t"), date: Optional[str] = typer.Option(None, "--date"), language: Optional[str] = typer.Option(None, "--language")) -> None:
    """Generate a daily research memo in zh-CN or English."""

    result = render_daily_memo(paths(target), date=date, language=language)
    sync_dashboard(paths(target))
    console.print_json(data={"path": result["path"], "json_path": result["json_path"]})


@dashboard_app.command("export-research")
def dashboard_export_research_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Export research registry, graph, portfolio, and budget JSON for future visualization."""

    result = export_research_dashboard(paths(target))
    export_readiness_dashboard(paths(target))
    console.print_json(data=result)


@app.command("validate-decision")
def validate_decision_cmd(target_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Validate a structured run or cycle decision JSON file."""

    issues = validate_decision_file(paths(target), target_id)
    if issues:
        for issue in issues:
            console.print(f"[error] {issue}")
        raise typer.Exit(1)
    console.print(f"Decision OK: {target_id}")


@decision_app.command("show")
def decision_show(target_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Print structured run or cycle decision JSON."""

    console.print(decision_json(paths(target), target_id))


@decision_app.command("write-block")
def decision_write_block(
    target_id: str,
    reason: str = typer.Option(..., "--reason"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    decision_type: str = typer.Option("blocked_missing_decision", "--decision-type"),
) -> None:
    """Write an explicit block decision for operator recovery."""

    write_block_decision(paths(target), target_id, reason, decision_type=decision_type)  # type: ignore[arg-type]
    console.print(f"Blocked {target_id}: {reason}")


@decision_app.command("write")
def decision_write(
    target_id: str,
    decision_type: str = typer.Option("launch_gpu_gate", "--type"),
    action: str = typer.Option(..., "--action"),
    rationale: str = typer.Option("", "--rationale"),
    direction: str = typer.Option("", "--direction"),
    baseline: str = typer.Option("", "--baseline"),
    hypothesis_id: str = typer.Option("", "--hypothesis-id"),
    experiment_id: str = typer.Option("", "--experiment-id"),
    policy_eval_id: str = typer.Option("", "--policy-eval-id"),
    budget_reservation_id: str = typer.Option("", "--budget-reservation-id"),
    stage: str = typer.Option("", "--stage"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Write a structured non-block decision for adapter compilation."""

    decision = make_decision(
        paths(target),
        target_id,
        decision_type,  # type: ignore[arg-type]
        rationale=rationale or action,
        selected_direction=direction,
        required_action=action,
        baseline_comparison_target=baseline or ("trusted_baseline" if decision_type == "promote_to_baseline_compare" else ""),
        hypothesis_id=hypothesis_id,
        experiment_id=experiment_id,
        policy_eval_id=policy_eval_id,
        budget_reservation_id=budget_reservation_id,
        stage=stage,
        provenance={"source": "operator_cli"},
    )
    write_decision(paths(target), decision)
    console.print(f"Wrote decision {decision.decision_id} for {target_id}: {decision.decision_type}")


@app.command("compile-decision")
def compile_decision_cmd(cycle_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Compile a structured cycle decision into an executable resource plan."""

    ok, message = compile_cycle_decision(paths(target), cycle_id)
    if not ok:
        console.print(f"[error] {message}")
        raise typer.Exit(1)
    console.print(f"Compiled {cycle_id}: {message}")


@app.command("validate-resource-plan")
def validate_resource_plan_cmd(cycle_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Validate compiled resource plan executability and trust metadata."""

    issues = validate_resource_plan(paths(target), cycle_id)
    if issues:
        for issue in issues:
            console.print(f"[error] {issue}")
        raise typer.Exit(1)
    console.print(f"Resource plan OK: {cycle_id}")


@config_app.command("show")
def config_show(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Print the merged generated, JSON mirror, and local config."""

    p = paths(target)
    p.require_initialized()
    console.print_json(data=load_config(p))


@config_app.command("validate")
def config_validate(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Validate config files against the current schema."""

    p = paths(target)
    p.require_initialized()
    issues = validate_config(p)
    if issues:
        for issue in issues:
            console.print(f"[error] {issue}")
        raise typer.Exit(1)
    console.print("Config OK")


@config_app.command("detect")
def config_detect(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Probe local environment and write .vibe/config.detected.yaml."""

    p = paths(target)
    p.require_initialized()
    detected = detect_config(p, write=True)
    console.print(f"Wrote {p.vibe / 'config.detected.yaml'}")
    console.print_json(data=detected.get("suggested_config", {}))


@config_app.command("edit")
def config_edit(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    local: bool = typer.Option(False, "--local", help="Edit config.local.yaml instead of config.yaml."),
) -> None:
    """Open the config file in $EDITOR, or print its path when no editor is set."""

    p = paths(target)
    p.require_initialized()
    path = p.vibe / ("config.local.yaml" if local else "config.yaml")
    if not path.exists():
        path.write_text("{}\n")
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL")
    if not editor:
        console.print(str(path))
        return
    raise typer.Exit(subprocess.call([editor, str(path)]))


@portal_app.command("build")
def portal_build(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    mode: Optional[str] = typer.Option(None, "--mode", help="Override configured mode: copy, symlink, or none."),
    force: bool = typer.Option(False, "--force", help="Overwrite existing managed mirrors."),
) -> None:
    """Rebuild root mirror files from .vibe/portal."""

    p = paths(target)
    p.require_initialized()
    written = build_portal(p, mode=mode, force=force)
    console.print(f"Built {len(written)} root portal mirror(s)")


@dashboard_app.command("build")
def dashboard_build(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Build the read-only static dashboard."""

    index = build_dashboard_site(paths(target))
    console.print(f"Built {index}")


@dashboard_app.command("serve")
def dashboard_serve(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
    once: bool = typer.Option(False, "--once", help="Build and print URL without blocking; useful for smoke tests."),
) -> None:
    """Serve the read-only static dashboard on a local interface."""

    console.print(serve_dashboard_site(paths(target), host=host, port=port, once=once))


@audit_app.command("current")
def audit_current(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Write the current alignment audit report."""

    report = current_alignment_audit(paths(target))
    console.print(f"Wrote {report}")


@app.command("export-meeting")
def export_meeting_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    date: Optional[str] = typer.Option(None, "--date", help="YYYYMMDD output folder name."),
) -> None:
    """Export a meeting story pack from existing local evidence."""

    out = export_meeting_report(paths(target), date=date)
    console.print(f"Exported {out}")


@app.command("dogfood")
def dogfood_cmd(target: Optional[Path] = typer.Option(None, "--target", "-t", help="Optional target; defaults to a temp repo.")) -> None:
    """Run a cheap local/mock dogfood cycle and generate reports."""

    from .reports import dogfood_mock_cycle

    result = dogfood_mock_cycle(target)
    console.print_json(data=result)


@app.command("finalize-reports")
def finalize_reports_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Generate final alignment, test-summary placeholder, portal docs, dashboard, and meeting report."""

    result = generate_dogfood_reports(paths(target))
    console.print_json(data=result)


@app.command()
def migrate(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Migrate existing `.vibe` config/state to the current schema."""

    p = paths(target)
    p.require_initialized()
    migrate_project(p)
    sync_dashboard(p)
    console.print("Migrated VibeResearch state")


@app.command()
def status(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Show current cycle, runs, scheduler, and next action."""

    p = paths(target)
    p.require_initialized()
    sync_dashboard(p)
    console.print(render_status(p))
    table = Table(title="Runs")
    table.add_column("Run")
    table.add_column("Direction")
    table.add_column("Status")
    table.add_column("Branch")
    state = read_json(p.state / "state.json", {})
    for run_id, run in sorted(state.get("runs", {}).items()):
        table.add_row(run_id, run.get("direction_id", ""), run.get("status", ""), run.get("branch", ""))
    if state.get("runs"):
        console.print(table)


@app.command()
def next(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Tell the operator the next recommended command."""

    p = paths(target)
    p.require_initialized()
    action, computed_block = compute_next_action(p)
    state = read_json(p.state / "state.json", {})
    blocked = computed_block or state.get("blocked_reason", "")
    if blocked:
        console.print(f"[red]Blocked:[/red] {blocked}")
    console.print(f"Next: [bold]{action}[/bold]")


@app.command()
def idea(text: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Add a user idea to the inbox and triage log."""

    record = add_idea(paths(target), text)
    console.print(f"Recorded idea {record.idea_id}")


@app.command()
def ask(text: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Record a user question as an inbox idea-like prompt."""

    record = add_idea(paths(target), text, source="question")
    console.print(f"Recorded question {record.idea_id}")


@ideas_app.command("list")
def ideas_list(target: Path = typer.Option(Path("."), "--target", "-t"), status: Optional[str] = typer.Option(None, "--status")) -> None:
    """List maintained idea pool entries."""

    rows = read_ideas(paths(target))
    table = Table(title="Ideas")
    for col in ["Idea", "Status", "Priority", "Confidence", "Next action", "Text"]:
        table.add_column(col)
    for row in rows:
        if status and row.get("status") != status:
            continue
        table.add_row(
            row.get("idea_id", ""),
            row.get("status", ""),
            row.get("priority", ""),
            row.get("confidence", ""),
            row.get("next_action", ""),
            row.get("raw_text", "")[:80],
        )
    console.print(table)


@ideas_app.command("triage")
def ideas_triage(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Deterministically triage new idea pool entries."""

    changed = triage_ideas(paths(target))
    console.print(f"Triaged {len(changed)} idea(s)")


@ideas_app.command("promote")
def ideas_promote(idea_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Promote an idea into active planning."""

    row = promote_idea(paths(target), idea_id)
    sync_dashboard(paths(target))
    console.print(f"Promoted {row['idea_id']}")


@ideas_app.command("reject")
def ideas_reject(idea_id: str, target: Path = typer.Option(Path("."), "--target", "-t"), reason: str = typer.Option("", "--reason")) -> None:
    """Reject an idea with an optional reason."""

    row = reject_idea(paths(target), idea_id, reason)
    sync_dashboard(paths(target))
    console.print(f"Rejected {row['idea_id']}")


@ideas_app.command("archive")
def ideas_archive(idea_id: str, target: Path = typer.Option(Path("."), "--target", "-t"), reason: str = typer.Option("", "--reason")) -> None:
    """Archive an idea with an optional reason."""

    row = archive_pool_idea(paths(target), idea_id, reason)
    sync_dashboard(paths(target))
    console.print(f"Archived {row['idea_id']}")


@ideas_app.command("clean")
def ideas_clean(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Mark duplicate idea text as superseded and rebuild idea views."""

    result = clean_ideas(paths(target))
    sync_dashboard(paths(target))
    console.print(result)


@ideas_app.command("build-deep-request")
def ideas_build_deep_request(idea_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Build a contextual deep research request for an idea."""

    request_id = build_deep_request_from_idea(paths(target), idea_id)
    sync_dashboard(paths(target))
    console.print(f"Created {request_id}")


@app.command()
def directive(text: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Add a temporary human directive for the next cycle."""

    add_directive(paths(target), text)
    console.print("Recorded directive")


@app.command("plan-cycle")
def plan_cycle(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    mode: Optional[str] = typer.Option(None, "--mode", help="exploration, balanced, or exploitation"),
    offline: bool = typer.Option(False, "--offline", help="Use deterministic fallback instead of Codex."),
) -> None:
    """Create a portfolio plan for the next cycle."""

    p = paths(target)
    try:
        cycle_id = create_cycle(p, mode=mode)
    except RuntimeError as exc:
        console.print(f"[error] {exc}")
        raise typer.Exit(1)
    result = run_codex(p, "portfolio_planner", cycle_id, offline=offline)
    issues = validate_artifact(p, "portfolio_planner", cycle_id)
    if issues:
        for issue in issues:
            console.print(f"[{issue.level}] {issue.message}")
        raise typer.Exit(1)
    sync_resource_plan_from_portfolio(p, cycle_id)
    console.print(f"Created cycle {cycle_id} via {'offline fallback' if offline else 'Codex'} ({result.call_id})")


@app.command("review-cycle")
def review_cycle_cmd(
    cycle_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    offline: bool = typer.Option(False, "--offline", help="Use deterministic fallback instead of Codex."),
) -> None:
    """Approve or guard a cycle-level portfolio scaffold."""

    p = paths(target)
    result = run_codex(p, "portfolio_reviewer", cycle_id, offline=offline)
    issues = validate_artifact(p, "portfolio_reviewer", cycle_id)
    if issues:
        for issue in issues:
            console.print(f"[{issue.level}] {issue.message}")
        raise typer.Exit(1)
    review_cycle(p, cycle_id)
    console.print(f"Reviewed {cycle_id} via {'offline fallback' if offline else 'Codex'} ({result.call_id})")


@app.command("generate-runs")
def generate_runs_cmd(
    cycle_id: Optional[str] = typer.Argument(None),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    count: int = typer.Option(3, "--count", min=1, max=6),
) -> None:
    """Generate run directories, proposals, manifests, and branch names."""

    try:
        run_ids = generate_runs(paths(target), cycle_id=cycle_id, count=count)
    except RuntimeError as exc:
        console.print(f"[error] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"Generated runs: {', '.join(run_ids)}")


@app.command()
def review(
    run_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    offline: bool = typer.Option(False, "--offline", help="Use deterministic fallback instead of Codex."),
) -> None:
    """Write a guarded run review scaffold."""

    p = paths(target)
    result = run_codex(p, "reviewer", run_id, offline=offline)
    issues = validate_artifact(p, "reviewer", run_id)
    if issues:
        for issue in issues:
            console.print(f"[{issue.level}] {issue.message}")
        raise typer.Exit(1)
    review_run(p, run_id)
    console.print(f"Reviewed {run_id} via {'offline fallback' if offline else 'Codex'} ({result.call_id})")


@app.command()
def branch(run_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Create or record the per-run branch."""

    name = create_branch(paths(target), run_id)
    console.print(f"Branch ready: {name}")


@app.command()
def patch(
    run_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    offline: bool = typer.Option(False, "--offline", help="Use deterministic fallback instead of Codex."),
    record_only: bool = typer.Option(False, "--record-only", help="Record the current diff without invoking Codex."),
) -> None:
    """Generate or record the bounded patch artifact for a run."""

    p = paths(target)
    p.require_initialized()
    state = read_json(p.state / "state.json", {})
    run = state.get("runs", {}).get(run_id)
    if not run:
        raise typer.BadParameter(f"Unknown run: {run_id}")
    issues = validate_manifest(p, run_id)
    if any(issue.level == "error" for issue in issues):
        for issue in issues:
            console.print(f"[{issue.level}] {issue.message}")
        raise typer.Exit(1)
    if git_available(p.root):
        branch = git_current_branch(p.root)
        if branch and branch != run.get("branch"):
            console.print(f"[error] current branch `{branch}` does not match run branch `{run.get('branch')}`")
            raise typer.Exit(1)
    patch_path = p.runs / run_id / "patch.diff"
    if record_only:
        patch_path.write_text(git_diff_text(p.root))
        call_id = "record-only"
    else:
        result = run_codex(p, "codex_patch", run_id, offline=offline)
        call_id = result.call_id
    diff_text = patch_path.read_text() if patch_path.exists() else ""
    protected = protected_diff_paths(diff_text)
    if protected:
        console.print(f"[error] patch touches protected paths: {', '.join(protected)}")
        raise typer.Exit(1)
    state = read_json(p.state / "state.json", {})
    state.setdefault("runs", {}).setdefault(run_id, {})["status"] = "patched"
    state["next_action"] = f"vibe dryrun {run_id}"
    from .io import write_json

    write_json(p.state / "state.json", state)
    console.print(f"Patch artifact: {patch_path} ({call_id})")


@app.command()
def dryrun(run_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Run the manifest dry-run command."""

    result = run_dryrun(paths(target), run_id)
    console.print(f"Dry-run {run_id}: returncode={result['returncode']}")


@app.command()
def queue(run_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Queue a run for deterministic scheduler submission."""

    try:
        queue_run(paths(target), run_id)
    except RuntimeError as exc:
        console.print(f"[error] {exc}")
        raise typer.Exit(1) from exc
    console.print(f"Queued {run_id}")


@app.command("submit-queue")
def submit_queue_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    dry: bool = typer.Option(False, "--dry", help="Record submissions without launching processes."),
    backend: Optional[str] = typer.Option(None, "--backend", help="local or slurm; defaults to config."),
) -> None:
    """Submit queued runs within scheduler budget."""

    submitted = submit_queue(paths(target), dry=dry, backend_name=backend)
    console.print(f"Submitted: {', '.join(submitted) if submitted else 'none'}")


@app.command()
def monitor(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    loop: bool = typer.Option(False, "--loop"),
    interval: int = typer.Option(300, "--interval", min=1),
    auto_next: bool = typer.Option(False, "--auto-next"),
    iterations: Optional[int] = typer.Option(None, "--iterations", help="Testing guard for loop mode."),
) -> None:
    """Poll active jobs without LLM calls."""

    p = paths(target)
    count = 0
    while True:
        monitor_jobs(p, auto_next=auto_next)
        console.print("Monitor pass complete")
        count += 1
        if not loop or (iterations is not None and count >= iterations):
            break
        time.sleep(interval)


@app.command()
def collect(
    run_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    metric: Optional[float] = typer.Option(None, "--metric"),
    metrics_file: Optional[Path] = typer.Option(None, "--metrics-file"),
    trusted: bool = typer.Option(False, "--trusted/--candidate"),
) -> None:
    """Collect metrics and update leaderboard history."""

    collect_run(paths(target), run_id, metric=metric, metrics_file=str(metrics_file) if metrics_file else None, trusted=trusted)
    console.print(f"Collected {run_id}")


@app.command()
def cancel(run_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Cancel an active local or Slurm job."""

    result = cancel_run(paths(target), run_id)
    console.print(result)


@app.command("scheduler-status")
def scheduler_status(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Show queue and active job tables."""

    p = paths(target)
    queue = read_json(p.scheduler / "queue.json", {"queued": []}).get("queued", [])
    active = read_json(p.scheduler / "active_jobs.json", {"active": []}).get("active", [])
    completed = read_jsonl(p.scheduler / "completed_jobs.jsonl")
    daemon = daemon_status(p)
    console.print(f"Daemon running: {daemon.get('running', False)} session={daemon.get('session', '')}")
    console.print(f"Queued={len(queue)} Active={len(active)} Completed={len(completed)} Next collect={', '.join(daemon.get('next_collection_runs', [])) or 'none'}")
    table = Table(title="Scheduler")
    table.add_column("Kind")
    table.add_column("Run")
    table.add_column("Status")
    table.add_column("Backend")
    table.add_column("Job")
    for row in queue:
        table.add_row("queued", row.get("run_id", ""), row.get("status", ""), "", "")
    for row in active:
        table.add_row("active", row.get("run_id", ""), row.get("status", ""), row.get("backend", ""), row.get("job_id", ""))
    console.print(table)


@app.command("scheduler-explain")
def scheduler_explain_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Explain scheduler decisions and current waits."""

    console.print(render_scheduler_explain(paths(target)))


@app.command("auto-next")
def auto_next_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    offline: bool = typer.Option(False, "--offline"),
    dry_submit: bool = typer.Option(True, "--dry-submit/--real-submit"),
) -> None:
    """Execute one safe next step from the local state machine."""

    console.print(run_auto_next(paths(target), offline=offline, dry_submit=dry_submit))


@app.command("auto-cycle")
def auto_cycle_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    offline: bool = typer.Option(False, "--offline"),
    dry_submit: bool = typer.Option(True, "--dry-submit/--real-submit"),
    max_steps: int = typer.Option(30, "--max-steps"),
) -> None:
    """Advance one portfolio cycle until submit/manual/block."""

    for line in run_auto_cycle(paths(target), offline=offline, dry_submit=dry_submit, max_steps=max_steps):
        console.print(line)


@app.command("validate-manifest")
def validate_manifest_cmd(run_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Validate manifest schema, commands, and required resources."""

    issues = validate_manifest(paths(target), run_id)
    if not issues:
        console.print("Manifest OK")
        return
    for issue in issues:
        console.print(f"[{issue.level}] {issue.message}")
    if any(issue.level == "error" for issue in issues):
        raise typer.Exit(1)


@app.command("validate-artifact")
def validate_artifact_cmd(role: str, target_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Validate a Codex/deterministic artifact contract."""

    issues = validate_artifact(paths(target), role, target_id)
    if not issues:
        console.print("Artifact OK")
        return
    for issue in issues:
        console.print(f"[{issue.level}] {issue.message}")
    if any(issue.level == "error" for issue in issues):
        raise typer.Exit(1)


@app.command("validate-hard-rules")
def validate_hard_rules_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Validate TODO.md hard rules against current state."""

    issues = validate_hard_rules(paths(target))
    if not issues:
        console.print("Hard rules OK")
        return
    for issue in issues:
        console.print(f"[{issue.level}] {issue.message}")
    if any(issue.level == "error" for issue in issues):
        raise typer.Exit(1)


direction_app = typer.Typer(help="Manage research direction states.")
app.add_typer(direction_app, name="direction")


@direction_app.command("pause")
def direction_pause(direction_id: str, reason: str = typer.Option("", "--reason"), target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    set_direction_status(paths(target), direction_id, "paused", reason)
    console.print(f"Paused {direction_id}")


@direction_app.command("promote")
def direction_promote(direction_id: str, reason: str = typer.Option("", "--reason"), target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    set_direction_status(paths(target), direction_id, "promoted", reason)
    console.print(f"Promoted {direction_id}")


@direction_app.command("stop")
def direction_stop(direction_id: str, reason: str = typer.Option("", "--reason"), target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    set_direction_status(paths(target), direction_id, "stopped", reason)
    console.print(f"Stopped {direction_id}")


def reflect_cmd(
    run_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    offline: bool = typer.Option(False, "--offline", help="Use deterministic fallback instead of Codex."),
) -> None:
    """Generate run-level reflection."""

    p = paths(target)
    result = run_codex(p, "reflect", run_id, offline=offline)
    issues = validate_artifact(p, "reflect", run_id)
    if issues:
        for issue in issues:
            console.print(f"[{issue.level}] {issue.message}")
        raise typer.Exit(1)
    reflect(p, run_id, keep_existing=True)
    console.print(f"Reflected {run_id} via {'offline fallback' if offline else 'Codex'} ({result.call_id})")


app.command("reflect")(reflect_cmd)


@app.command("revise-plan")
def revise_plan_cmd(
    run_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    decision: str = typer.Option("collect_more_metrics", "--decision"),
    offline: bool = typer.Option(False, "--offline", help="Use deterministic fallback instead of Codex."),
) -> None:
    """Generate mandatory run-level revised plan."""

    p = paths(target)
    result = run_codex(p, "revised_plan", run_id, offline=offline)
    issues = validate_artifact(p, "revised_plan", run_id)
    if issues:
        for issue in issues:
            console.print(f"[{issue.level}] {issue.message}")
        raise typer.Exit(1)
    revise_plan(p, run_id, decision=decision, keep_existing=True, offline=offline)
    console.print(f"Revised plan for {run_id} via {'offline fallback' if offline else 'Codex'} ({result.call_id})")


@app.command("reflect-cycle")
def reflect_cycle_cmd(
    cycle_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    offline: bool = typer.Option(False, "--offline", help="Use deterministic fallback instead of Codex."),
) -> None:
    """Generate cycle-level reflection."""

    p = paths(target)
    result = run_codex(p, "cycle_reflect", cycle_id, offline=offline)
    issues = validate_artifact(p, "cycle_reflect", cycle_id)
    if issues:
        for issue in issues:
            console.print(f"[{issue.level}] {issue.message}")
        raise typer.Exit(1)
    reflect_cycle(p, cycle_id, keep_existing=True)
    console.print(f"Reflected cycle {cycle_id} via {'offline fallback' if offline else 'Codex'} ({result.call_id})")


@app.command("revise-cycle")
def revise_cycle_cmd(
    cycle_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    mode: Optional[str] = typer.Option(None, "--mode"),
    offline: bool = typer.Option(False, "--offline", help="Use deterministic fallback instead of Codex."),
) -> None:
    """Generate mandatory cycle-level revised plan."""

    p = paths(target)
    result = run_codex(p, "cycle_revised_plan", cycle_id, offline=offline)
    issues = validate_artifact(p, "cycle_revised_plan", cycle_id)
    if issues:
        for issue in issues:
            console.print(f"[{issue.level}] {issue.message}")
        raise typer.Exit(1)
    revise_cycle(p, cycle_id, mode=mode, keep_existing=True, offline=offline)
    console.print(f"Revised cycle {cycle_id} via {'offline fallback' if offline else 'Codex'} ({result.call_id})")


@app.command("lit-refresh")
def lit_refresh_cmd(
    run_id: Optional[str] = typer.Argument(None),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    query: str = typer.Option("", "--query"),
) -> None:
    """Record a targeted literature refresh result scaffold."""

    literature_refresh(paths(target), run_id=run_id, query=query)
    console.print("Literature refresh recorded")


@app.command("lit-refresh-cycle")
def lit_refresh_cycle_cmd(
    cycle_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    query: str = typer.Option("", "--query"),
) -> None:
    """Record a cycle-level literature refresh result scaffold."""

    literature_refresh(paths(target), cycle_id=cycle_id, query=query)
    console.print("Cycle literature refresh recorded")


@app.command("deep-request")
def deep_request_cmd(
    topic: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    run_id: str = typer.Option("", "--run-id"),
    blocking: bool = typer.Option(False, "--blocking"),
    offline: bool = typer.Option(False, "--offline"),
) -> None:
    """Generate a standard deep research request."""

    p = paths(target)
    request_for = run_id
    request_topic = topic
    if not request_for and topic.startswith("r"):
        request_for = topic
        request_topic = "route-level uncertainty"
    request_id = deep_request(p, request_for=request_for, topic=request_topic, blocking=blocking)
    run_codex(p, "deep_research_request", request_id, offline=offline)
    console.print(f"Created {request_id}")


@app.command("deep-request-cycle")
def deep_request_cycle_cmd(
    cycle_id: str,
    topic: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    blocking: bool = typer.Option(False, "--blocking"),
    offline: bool = typer.Option(False, "--offline"),
) -> None:
    """Generate a cycle-level deep research request."""

    p = paths(target)
    request_id = deep_request(p, request_for=cycle_id, topic=topic, blocking=blocking)
    run_codex(p, "deep_research_request", request_id, offline=offline)
    console.print(f"Created {request_id}")


@app.command("deep-request-from-idea")
def deep_request_from_idea_cmd(
    idea_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    offline: bool = typer.Option(False, "--offline"),
) -> None:
    """Generate a contextual deep research request from a maintained idea."""

    p = paths(target)
    del offline
    get_idea(p, idea_id)
    request_id = build_deep_request_from_idea(p, idea_id)
    sync_dashboard(p)
    console.print(f"Created {request_id}")


@app.command("ingest-deep-research")
def ingest_deep_research_cmd(
    request_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    kind: str = typer.Option("science", "--kind", help="science, workflow, repo, or benchmark"),
) -> None:
    """Ingest a returned deep research report from raw/deep_reports."""

    if kind not in {"science", "workflow", "repo", "benchmark"}:
        raise typer.BadParameter("--kind must be science, workflow, repo, or benchmark")
    ingest_deep_research(paths(target), request_id, kind=kind)
    console.print(f"Ingested {request_id}")


@app.command("wiki-ingest")
def wiki_ingest(
    paper_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    offline: bool = typer.Option(False, "--offline"),
) -> None:
    """Ingest a paper metadata record into the local research wiki."""

    p = paths(target)
    p.require_initialized()
    run_codex(p, "paper_ingest", paper_id, offline=offline)
    note = wiki_ingest_paper(p, paper_id)
    sync_dashboard(p)
    console.print(f"Created {note}")


@app.command("paper-ingest")
def paper_ingest(paper_id: str, target: Path = typer.Option(Path("."), "--target", "-t"), offline: bool = typer.Option(False, "--offline")) -> None:
    """Alias for paper-to-wiki ingest."""

    wiki_ingest(paper_id, target=target, offline=offline)


@app.command("paper-search")
def paper_search_cmd(
    query: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    source: str = typer.Option("arxiv", "--source"),
    limit: int = typer.Option(10, "--limit"),
    offline: bool = typer.Option(False, "--offline"),
    add_candidates: bool = typer.Option(False, "--add-candidates", help="Add returned records as paper DB candidates."),
) -> None:
    """Search papers and record search provenance."""

    results = paper_search(paths(target), query, source=source, limit=limit, offline=offline, add_candidates=add_candidates)
    for row in results:
        console.print(row)


@app.command("paper-add")
def paper_add_cmd(
    title: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    source_url: str = typer.Option("", "--source-url"),
    pdf_url: str = typer.Option("", "--pdf-url"),
) -> None:
    """Add a paper metadata record to papers.sqlite."""

    paper_id = add_paper(paths(target), {"title": title, "source_url": source_url, "pdf_url": pdf_url})
    console.print(paper_id)


@app.command("paper-download")
def paper_download_cmd(paper_id: str, url: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Download a paper PDF and record checksum provenance."""

    metadata = download_paper(paths(target), paper_id, url)
    pdf_to_markdown(paths(target), paper_id)
    console.print(metadata)


@app.command("paper-list")
def paper_list_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """List local paper DB records."""

    table = Table(title="Papers")
    for col in ["paper_id", "title", "year", "status", "sha256"]:
        table.add_column(col)
    for row in list_papers(paths(target)):
        table.add_row(row["paper_id"], row["title"], row["year"], row["status"], row["sha256"][:12])
    console.print(table)


@app.command("wiki-lint")
def wiki_lint(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Check for required wiki entrypoint files."""

    p = paths(target)
    missing = [str(path) for path in [p.research / "wiki" / "index.md", p.research / "wiki" / "log.md"] if not path.exists()]
    if missing:
        for item in missing:
            console.print(f"missing {item}")
        raise typer.Exit(1)
    console.print("Wiki OK")


@app.command("codex-prompt")
def codex_prompt(role: str, target_id: str = "", target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Print the bounded Codex artifact-generation prompt packet."""

    console.print(prompt_packet(paths(target), role, target_id))


@app.command("codex-artifact")
def codex_artifact(role: str, target_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Show where a Codex-generated artifact should be written."""

    console.print(str(artifact_path(paths(target), role, target_id)))


def print_codex_packet(role: str, target_id: str, target: Path) -> None:
    p = paths(target)
    console.print(prompt_packet(p, role, target_id))
    console.print(f"\nArtifact path: {artifact_path(p, role, target_id)}")


@app.command("codex-plan")
def codex_plan(
    target_id: str = typer.Argument(""),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    offline: bool = typer.Option(False, "--offline"),
) -> None:
    """Generate a Codex portfolio plan artifact."""

    result = run_codex(paths(target), "portfolio_planner", target_id, offline=offline)
    console.print(f"Wrote {result.artifact_path} ({result.call_id})")


@app.command("codex-review")
def codex_review(target_id: str, target: Path = typer.Option(Path("."), "--target", "-t"), offline: bool = typer.Option(False, "--offline")) -> None:
    """Generate a Codex portfolio/run review artifact."""

    role = "portfolio_reviewer" if target_id.startswith("c") else "reviewer"
    result = run_codex(paths(target), role, target_id, offline=offline)
    console.print(f"Wrote {result.artifact_path} ({result.call_id})")


@app.command("codex-patch")
def codex_patch(target_id: str, target: Path = typer.Option(Path("."), "--target", "-t"), offline: bool = typer.Option(False, "--offline")) -> None:
    """Generate bounded patch artifact with Codex."""

    result = run_codex(paths(target), "codex_patch", target_id, offline=offline)
    console.print(f"Wrote {result.artifact_path} ({result.call_id})")


@app.command("codex-reflect")
def codex_reflect(target_id: str, target: Path = typer.Option(Path("."), "--target", "-t"), offline: bool = typer.Option(False, "--offline")) -> None:
    """Generate Codex run/cycle reflection artifact."""

    role = "cycle_reflect" if target_id.startswith("c") else "reflect"
    result = run_codex(paths(target), role, target_id, offline=offline)
    console.print(f"Wrote {result.artifact_path} ({result.call_id})")


@app.command("codex-revise")
def codex_revise(target_id: str, target: Path = typer.Option(Path("."), "--target", "-t"), offline: bool = typer.Option(False, "--offline")) -> None:
    """Generate Codex run/cycle revised planning artifact."""

    role = "cycle_revised_plan" if target_id.startswith("c") else "revised_plan"
    result = run_codex(paths(target), role, target_id, offline=offline)
    console.print(f"Wrote {result.artifact_path} ({result.call_id})")


@app.command("codex-call")
def codex_call(role: str, target_id: str = "", target: Path = typer.Option(Path("."), "--target", "-t"), offline: bool = typer.Option(False, "--offline")) -> None:
    """Run an arbitrary bounded Codex artifact role."""

    result = run_codex(paths(target), role, target_id, offline=offline)
    console.print(f"Wrote {result.artifact_path} ({result.call_id})")


@app.command()
def leaderboard(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Show leaderboard markdown."""

    p = paths(target)
    p.require_initialized()
    sync_dashboard(p)
    console.print(render_leaderboard(p))


@app.command()
def timeline(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Show and regenerate timeline markdown/html/svg."""

    p = paths(target)
    p.require_initialized()
    sync_timeline_files(p)
    console.print(render_timeline_markdown(p))


@app.command()
def merge(
    run_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    override: bool = typer.Option(False, "--override"),
) -> None:
    """Record a reviewed merge."""

    merge_run(paths(target), run_id, override=override)
    sync_dashboard(paths(target))
    console.print(f"Merged {run_id}")


@app.command("merge-review")
def merge_review_cmd(run_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Check whether a run is eligible to merge."""

    verdict = merge_review(paths(target), run_id)
    sync_dashboard(paths(target))
    console.print(verdict)


@app.command()
def abandon(
    run_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    reason: str = typer.Option("", "--reason"),
) -> None:
    """Record an abandoned run."""

    abandon_run(paths(target), run_id, reason)
    sync_dashboard(paths(target))
    console.print(f"Abandoned {run_id}")


@daemon_app.command("start")
def daemon_start_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    interval: Optional[int] = typer.Option(None, "--interval"),
    auto_next: bool = typer.Option(True, "--auto-next/--no-auto-next"),
) -> None:
    """Start a tmux supervisor running monitor --loop."""

    console.print(daemon_start(paths(target), interval=interval, auto_next=auto_next))


@daemon_app.command("stop")
def daemon_stop_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Stop the tmux supervisor."""

    console.print(daemon_stop(paths(target)))


@daemon_app.command("status")
def daemon_status_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Show tmux supervisor status."""

    console.print(daemon_status(paths(target)))


@daemon_app.command("logs")
def daemon_logs_cmd(target: Path = typer.Option(Path("."), "--target", "-t"), lines: int = typer.Option(80, "--lines")) -> None:
    """Tail daemon log text."""

    log = paths(target).dashboard / "daemon.log"
    if not log.exists():
        console.print("No daemon log yet")
        return
    console.print("\n".join(log.read_text().splitlines()[-lines:]))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
