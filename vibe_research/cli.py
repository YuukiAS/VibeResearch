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
    apply_project_adapter_profile,
    detect_project_adapter_profile,
    run_contract_test,
    script_bootstrap,
    write_real_experiment_gap_report,
)
from .anti_stall import run_anti_stall_benchmark, validate_anti_stall_report
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
from .belief_ratchet import apply_belief_ratchet, load_ratchet_record, validate_ratchet_record
from .codex_adapter import artifact_path, prompt_packet, run_codex
from .compiler import compile_reviewed_plan, load_reviewed_plan, validate_execution_manifest, write_execution_package
from .config import detect_config, load_config, migrate_project, validate_config
from .convergence import close_convergence_budget, dependency_audit, freeze_check, record_override, risk_gate, set_convergence_stage, write_known_risk_review
from .daemon import daemon_autonomy_audit, daemon_start, daemon_status, daemon_stop
from .dashboard import render_leaderboard, render_status, sync_dashboard
from .dashboard_site import build_dashboard_site, serve_dashboard_site
from .decision_debt import clear_expired_decision_debts, load_debt_state, load_open_decision_debts, validate_debt_record
from .decisions import decision_json, make_decision, validate_decision_file, write_block_decision, write_decision
from .directions import set_direction_status
from .dual_track import create_track_experiment, parallel_comparison_plan, track_budget_audit, track_memo, track_transition_audit
from .external_resources import analyze_external_repo, clone_external_repo
from .executor import load_execution_manifest, run_execution_manifest, validate_boundary_guard, validate_result_manifest
from .git_ops import abandon_run, create_branch, git_available, git_current_branch, git_diff_text, merge_review, merge_run, protected_diff_paths
from .ideas import archive_idea as archive_pool_idea
from .ideas import build_deep_request_from_idea
from .ideas import clean_ideas, get_idea, promote_idea, read_ideas, reject_idea, triage_ideas
from .io import read_json, read_jsonl, read_yaml
from .immune_registry import immune_check, load_budget_recovery, record_registry_event
from .knowledge_lifecycle import advance_knowledge_ttl, load_orphan_audit, orphan_audit, record_knowledge_event
from .kernel import SESSION_ROLES, check_role_permission
from .kernel import check_protocol as kernel_check_protocol
from .kernel import initialize_kernel, kernel_status, record_evidence
from .locks import active_advance_lock
from .internalization import (
    add_external_asset,
    add_lineage_relation,
    build_lineage_memory,
    create_framework_proposal,
    internalization_readiness,
    record_internalization_decision,
)
from .manifest import validate_manifest
from .meeting import export_meeting_report
from .mve import load_manifest as load_mve_manifest
from .mve import promotion_debt_for_success, validate_mve_completion, validate_mve_contract, write_promotion_debt
from .next_action import compute_next_action
from .owned import owned_contract, owned_design_audit, owned_shadow_plan, scaffold_owned_framework
from .optimization import external_deemphasis_plan, plan_ablation, promote_champion, record_optimization_memory, record_regression_suite, register_challenger
from .os_beta import run_closed_loop_harness, validate_closed_loop
from .papers import add_paper, auto_method_search, download_paper, list_papers, paper_search, pdf_to_markdown, wiki_ingest_paper
from .paths import VibePaths
from .planner import build_draft_from_mechanism_card, build_draft_plan, load_draft_plan, validate_draft_plan, write_draft_plan
from .portal import build_portal
from .presentation import build_framework_spec, build_narrative, build_presentation_package, build_reproducibility_package, export_presentation_tables
from .project import add_directive, add_idea, create_cycle, generate_runs, init_project, sync_resource_plan_from_portfolio, vendor_runtime
from .promotion import compile_decision as compile_cycle_decision
from .promotion import validate_resource_plan
from .research import deep_request, ingest_deep_research, literature_refresh, literature_refresh_idea, reflect, reflect_cycle, revise_cycle, revise_plan
from .reviewer import review_draft_file, write_review_outputs
from .revision import build_revision_packet, load_revision_packet, resubmit_draft, write_resubmitted_draft, write_revision_packet
from .reports import generate_alignment_after_changes, generate_dogfood_reports, write_portal_docs
from .research_manager import (
    add_evidence,
    answer_research_question,
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
    sustained_round_audit,
)
from .real_experiments import summarize_real_experiment_progress
from .reflector import load_reflection, reflect_executor_result, validate_reflection
from .reliability import compare_checkpoints, reliability_checkpoint, reliability_doctor, reliability_report
from .scheduler import collect as collect_run
from .scheduler import cancel_run, monitor as monitor_jobs
from .scheduler import operator_fallback_requeue
from .scheduler import queue_run, review_cycle, review_run, run_dryrun, submit_queue
from .scout import add_scout_finding, create_mechanism_card, create_scout_claim, load_mechanism_card, scout_audit, scout_query_context, triage_scout_finding, validate_mechanism_card
from .selftests import sustained_round_selftest
from .session_budget_guard import (
    guard_session_action,
    initialize_budget_state,
    load_budget_state,
    record_zero_cost_wait,
    refresh_budget_from_status,
    write_low_budget_checkpoint,
)
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
compiler_app = typer.Typer(help="Compile accepted reviewed plans into execution manifests.")
executor_app = typer.Typer(help="Run accepted execution manifests and record executor provenance.")
kernel_app = typer.Typer(help="Manage the session-oriented research kernel.")
planner_app = typer.Typer(help="Generate reviewable Planner Session draft plans.")
reviewer_app = typer.Typer(help="Review Planner draft plans before compilation or execution.")
research_app = typer.Typer(help="Initialize and audit bounded autonomous research state.")
hypothesis_app = typer.Typer(help="Manage hypothesis registry records.")
experiment_app = typer.Typer(help="Manage experiment registry and evidence links.")
memory_app = typer.Typer(help="Build multi-cycle research memory packs.")
mve_app = typer.Typer(help="Validate minimum viable experiment contracts.")
portfolio_app = typer.Typer(help="Plan, schedule, and audit bounded experiment portfolios.")
policy_app = typer.Typer(help="Inspect and lint research policies.")
budget_app = typer.Typer(help="Reserve, reconcile, and inspect research budget.")
session_budget_app = typer.Typer(help="Manage Codex session quota guard state.")
memo_app = typer.Typer(help="Generate daily research memos.")
external_app = typer.Typer(help="Acquire external repositories and method resources with provenance.")
lineage_app = typer.Typer(help="Manage generic research lineage records.")
internalization_app = typer.Typer(help="Plan and audit generic internalization readiness.")
scout_app = typer.Typer(help="Triage scout findings into evidence-grade research inputs.")
owned_app = typer.Typer(help="Generate and audit downstream owned framework alpha scaffolds.")
optimize_app = typer.Typer(help="Manage champion/challenger owned optimization loops.")
present_app = typer.Typer(help="Export presentation-ready research packages.")
converge_app = typer.Typer(help="Control final convergence and freeze policy.")
reliability_app = typer.Typer(help="Run long-run reliability and soak diagnostics.")
reflector_app = typer.Typer(help="Interpret Executor outputs as an independent Reflector Session.")
ratchet_app = typer.Typer(help="Apply layered belief updates from Reflector outputs.")
registry_app = typer.Typer(help="Record and query research registry immune memory.")
debt_app = typer.Typer(help="Inspect and clear bounded WATCH/REFINE decision debt.")
knowledge_app = typer.Typer(help="Track knowledge lifecycle and clear orphan knowledge.")
os_beta_app = typer.Typer(help="Run and validate the OS beta closed-loop harness.")
anti_stall_app = typer.Typer(help="Run anti-stall benchmark traps and scoring.")
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
app.add_typer(compiler_app, name="compiler")
app.add_typer(executor_app, name="executor")
app.add_typer(kernel_app, name="kernel")
app.add_typer(planner_app, name="planner")
app.add_typer(reviewer_app, name="reviewer")
app.add_typer(research_app, name="research")
app.add_typer(hypothesis_app, name="hypothesis")
app.add_typer(experiment_app, name="experiment")
app.add_typer(memory_app, name="memory")
app.add_typer(mve_app, name="mve")
app.add_typer(portfolio_app, name="portfolio")
app.add_typer(policy_app, name="policy")
app.add_typer(budget_app, name="budget")
app.add_typer(session_budget_app, name="session-budget")
app.add_typer(memo_app, name="memo")
app.add_typer(external_app, name="external")
app.add_typer(lineage_app, name="lineage")
app.add_typer(internalization_app, name="internalization")
app.add_typer(scout_app, name="scout")
app.add_typer(owned_app, name="owned")
app.add_typer(optimize_app, name="optimize")
app.add_typer(present_app, name="present")
app.add_typer(converge_app, name="converge")
app.add_typer(reliability_app, name="reliability")
app.add_typer(reflector_app, name="reflector")
app.add_typer(ratchet_app, name="ratchet")
app.add_typer(registry_app, name="registry")
app.add_typer(debt_app, name="debt")
app.add_typer(knowledge_app, name="knowledge")
app.add_typer(os_beta_app, name="os-beta")
app.add_typer(anti_stall_app, name="anti-stall")
console = Console()


def effective_dry_submit(dry_submit: bool, real_submit: bool) -> bool:
    return bool((dry_submit or not real_submit) and not real_submit)


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
    preferred_partition: list[str] = typer.Option([], "--preferred-partition", help="Preferred Slurm partition; may be repeated in priority order."),
    fallback_partition: list[str] = typer.Option([], "--fallback-partition", help="Fallback Slurm partition; may be repeated in priority order."),
    partition_gres: list[str] = typer.Option([], "--partition-gres", help="Explicit Slurm GRES template as partition=gres, e.g. gpu_a100=gpu:a100:{gpu}. May be repeated."),
    max_pending_start_plus_run_hours: Optional[float] = typer.Option(None, "--max-pending-start-plus-run-hours", help="Maximum acceptable queued start plus requested runtime hours before fallback is preferred."),
    max_run_hours: Optional[float] = typer.Option(None, "--max-run-hours", help="Default per-experiment walltime cap for early runs."),
    mature_max_run_hours: Optional[float] = typer.Option(None, "--mature-max-run-hours", help="Relaxed per-experiment walltime cap for mature long-run capabilities."),
    delivery_max_run_hours: Optional[float] = typer.Option(None, "--delivery-max-run-hours", help="Final delivery/submission walltime cap; only for explicitly marked delivery-stage runs."),
    max_epochs: Optional[int] = typer.Option(None, "--max-epochs", help="Default epoch cap advertised to generated run resources."),
    delivery_max_epochs: Optional[int] = typer.Option(None, "--delivery-max-epochs", help="Final delivery/submission epoch cap; only for explicitly marked delivery-stage runs."),
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
        preferred_partitions=preferred_partition,
        fallback_partitions=fallback_partition,
        partition_gres=parse_partition_gres_options(partition_gres),
        max_pending_start_plus_run_hours=max_pending_start_plus_run_hours,
        max_run_hours_per_experiment=max_run_hours,
        mature_max_run_hours_per_experiment=mature_max_run_hours,
        delivery_max_run_hours_per_experiment=delivery_max_run_hours,
        max_epochs_per_experiment=max_epochs,
        delivery_max_epochs_per_experiment=delivery_max_epochs,
    )
    console.print(f"Initialized VibeResearch at [bold]{p.root}[/bold]")


def parse_partition_gres_options(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        partition, sep, gres = value.partition("=")
        if not sep or not partition.strip() or not gres.strip():
            raise typer.BadParameter("--partition-gres must use partition=gres-template")
        result[partition.strip()] = gres.strip()
    return result


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


@adapter_app.command("profile-detect")
def adapter_profile_detect_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Detect a repo-declared adapter profile by durable project evidence."""

    console.print_json(data=detect_project_adapter_profile(paths(target)))


@adapter_app.command("profile-apply")
def adapter_profile_apply_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Apply a matched repo-declared adapter profile."""

    p = paths(target)
    result = apply_project_adapter_profile(p)
    sync_dashboard(p)
    console.print_json(data=result)
    if not result.get("applied"):
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
    profile: str = typer.Option("0.8.8-happy-path", "--profile"),
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
def bootstrap_sandbox_cmd(target: Path = typer.Option(Path("."), "--target", "-t"), profile: str = typer.Option("0.8.8-happy-path", "--profile")) -> None:
    """Create one ignored local `.vibe_dogfood/` profile without running bootstrap."""

    path = create_local_dogfood_profile(paths(target).root, profile)
    console.print(str(path))


@compiler_app.command("compile")
def compiler_compile_cmd(
    reviewed: Optional[Path] = typer.Option(None, "--reviewed", help="Reviewed plan manifest; defaults to .vibe/kernel/reviewed_plan_manifest.json."),
    output: str = typer.Option("execution_manifest.json", "--output"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Compile an accepted reviewed plan into an execution package."""

    paths_ = paths(target)
    paths_.require_initialized()
    reviewed_path = reviewed or (paths_.kernel / "reviewed_plan_manifest.json")
    try:
        manifest = compile_reviewed_plan(paths_, load_reviewed_plan(reviewed_path))
        outputs = write_execution_package(paths_, manifest, output=output)
    except ValueError as exc:
        console.print(f"Compile rejected: {exc}")
        raise typer.Exit(1) from exc
    console.print(f"Execution manifest: {outputs['manifest']}")
    console.print(f"Script draft: {outputs['script']}")
    console.print(f"Slurm draft: {outputs['slurm_draft']}")


@compiler_app.command("validate")
def compiler_validate_cmd(manifest: Path = typer.Argument(..., help="Execution manifest JSON path to validate.")) -> None:
    """Validate a compiled execution manifest boundary contract."""

    issues = validate_execution_manifest(read_json(manifest, {}))
    console.print(f"Execution manifest validation: {'ok' if not issues else 'blocked'}")
    for issue in issues:
        console.print(f"Issue: {issue}")
    if issues:
        raise typer.Exit(1)


@executor_app.command("run")
def executor_run_cmd(
    manifest: Optional[Path] = typer.Argument(None, help="Execution manifest JSON path; defaults to .vibe/kernel/execution_manifest.json."),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    timeout_seconds: int = typer.Option(600, "--timeout-seconds"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Run an accepted execution manifest and write executor result records."""

    paths_ = paths(target)
    paths_.require_initialized()
    manifest_path = manifest or (paths_.kernel / "execution_manifest.json")
    try:
        result = run_execution_manifest(
            paths_,
            load_execution_manifest(manifest_path),
            manifest_path=manifest_path,
            timeout_seconds=timeout_seconds,
            dry_run=dry_run,
        )
    except FileNotFoundError as exc:
        console.print(str(exc))
        raise typer.Exit(1) from exc
    console.print(f"Executor result: {paths_.root / '.vibe' / 'executor' / 'result_manifest.json'}")
    console.print(f"Executor status: {result.get('status', 'unknown')}")
    if str(result.get("status", "")).startswith("blocked"):
        raise typer.Exit(1)


@executor_app.command("guard")
def executor_guard_cmd(
    manifest: Optional[Path] = typer.Argument(None, help="Execution manifest JSON path; defaults to .vibe/kernel/execution_manifest.json."),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Validate Executor boundary guard checks without running commands."""

    paths_ = paths(target)
    paths_.require_initialized()
    manifest_path = manifest or (paths_.kernel / "execution_manifest.json")
    try:
        issues = validate_boundary_guard(paths_, load_execution_manifest(manifest_path))
    except FileNotFoundError as exc:
        console.print(str(exc))
        raise typer.Exit(1) from exc
    console.print(f"Executor boundary guard: {'ok' if not issues else 'blocked'}")
    for issue in issues:
        console.print(f"Issue: {issue}")
    if issues:
        raise typer.Exit(1)


@executor_app.command("validate-result")
def executor_validate_result_cmd(
    result_manifest: Optional[Path] = typer.Argument(None, help="Executor result manifest; defaults to .vibe/executor/result_manifest.json."),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Validate that Executor output is complete and Reflector-readable."""

    paths_ = paths(target)
    result_path = result_manifest or (paths_.root / ".vibe" / "executor" / "result_manifest.json")
    issues = validate_result_manifest(paths_, read_json(result_path, {}))
    console.print(f"Executor result validation: {'ok' if not issues else 'blocked'}")
    for issue in issues:
        console.print(f"Issue: {issue}")
    if issues:
        raise typer.Exit(1)


@kernel_app.command("init")
def kernel_init_cmd(target: Path = typer.Option(Path("."), "--target", "-t"), force: bool = typer.Option(False, "--force")) -> None:
    """Create or repair the shared session-oriented research kernel files."""

    paths_ = paths(target)
    paths_.require_initialized()
    written = initialize_kernel(paths_, force=force)
    initialize_budget_state(paths_, force=force)
    console.print(f"Kernel initialized: {len(written)} file(s) written")


@session_budget_app.command("init")
def session_budget_init_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    session_name: str = typer.Option("", "--session-name"),
    role: str = typer.Option("", "--role"),
    resume_command: str = typer.Option("", "--resume-command"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Create or refresh SESSION_BUDGET_STATE.json and wait helper."""

    paths_ = paths(target)
    paths_.require_initialized()
    state_path = initialize_budget_state(paths_, force=force, session_name=session_name, role=role, resume_command=resume_command)
    console.print(f"Session budget state: {state_path}")


@session_budget_app.command("refresh")
def session_budget_refresh_cmd(
    status_text: Optional[str] = typer.Option(None, "--status-text", help="Text copied from codex --no-alt-screen /status."),
    status_file: Optional[Path] = typer.Option(None, "--status-file"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    session_name: str = typer.Option("", "--session-name"),
    role: str = typer.Option("", "--role"),
    estimated_reset_at: str = typer.Option("", "--estimated-reset-at"),
    resume_command: str = typer.Option("", "--resume-command"),
) -> None:
    """Refresh quota percentages from manually observed Codex status text."""

    paths_ = paths(target)
    paths_.require_initialized()
    text = status_text if status_text is not None else (status_file.read_text() if status_file else "")
    state = refresh_budget_from_status(
        paths_,
        status_text=text,
        session_name=session_name,
        role=role,
        estimated_reset_at=estimated_reset_at,
        resume_command=resume_command,
    )
    console.print_json(data=state)


@session_budget_app.command("guard")
def session_budget_guard_cmd(
    phase: str = typer.Option(..., "--phase", help="PLAN, REVIEW, COMPILE, EXECUTE, REFLECT, or SLEEP."),
    role: str = typer.Option("", "--role"),
    output: str = typer.Option("", "--output"),
    checkpoint_on_block: bool = typer.Option(False, "--checkpoint-on-block"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Check whether a role may enter a budget-sensitive phase."""

    paths_ = paths(target)
    paths_.require_initialized()
    result = guard_session_action(paths_, role=role, phase=phase, output_path=output, checkpoint_on_block=checkpoint_on_block)
    console.print(f"Session budget guard: {'ok' if result['ok'] else 'blocked'}")
    console.print(f"Phase: {result['phase']}")
    console.print(f"Role: {result['role']}")
    console.print(f"Action: {result['action']}")
    if result.get("checkpoint_path"):
        console.print(f"Checkpoint: {result['checkpoint_path']}")
    for reason in result["reasons"]:
        console.print(f"Reason: {reason}")
    if not result["ok"]:
        raise typer.Exit(1)


@session_budget_app.command("checkpoint")
def session_budget_checkpoint_cmd(
    phase: str = typer.Option(..., "--phase"),
    reason: list[str] = typer.Option([], "--reason"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Write a low-budget checkpoint and root RESUME.md."""

    paths_ = paths(target)
    paths_.require_initialized()
    checkpoint = write_low_budget_checkpoint(paths_, load_budget_state(paths_), phase=phase.upper(), reasons=reason)
    console.print_json(data=checkpoint)


@session_budget_app.command("wait-mode")
def session_budget_wait_mode_cmd(
    wait_type: str = typer.Option(..., "--wait-type", help="slurm-job or quota-wait."),
    job_id: str = typer.Option("", "--job-id"),
    estimated_reset_at: str = typer.Option("", "--estimated-reset-at"),
    resume_command: str = typer.Option("", "--resume-command"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Record a zero-cost wait state without polling from Codex."""

    paths_ = paths(target)
    paths_.require_initialized()
    try:
        record = record_zero_cost_wait(
            paths_,
            wait_type=wait_type,
            job_id=job_id,
            estimated_reset_at=estimated_reset_at,
            resume_command=resume_command,
        )
    except ValueError as exc:
        console.print(str(exc))
        raise typer.Exit(1) from exc
    console.print_json(data=record)


@reflector_app.command("reflect")
def reflector_reflect_cmd(
    result_manifest: Optional[Path] = typer.Option(None, "--result-manifest", help="Executor result manifest; defaults to .vibe/executor/result_manifest.json."),
    execution_manifest: Optional[Path] = typer.Option(None, "--execution-manifest", help="Execution manifest; defaults to .vibe/kernel/execution_manifest.json."),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Interpret Executor outputs and write reflect_report.md."""

    paths_ = paths(target)
    paths_.require_initialized()
    reflection = reflect_executor_result(paths_, result_manifest=result_manifest, execution_manifest=execution_manifest)
    console.print(f"Reflect verdict: {reflection.get('verdict', '')}")
    console.print(f"Reflect report: {paths_.kernel / 'reflect_report.md'}")
    if reflection.get("validation_issues"):
        for issue in reflection["validation_issues"]:
            console.print(f"Issue: {issue}")
        raise typer.Exit(1)


@reflector_app.command("validate")
def reflector_validate_cmd(reflection: Path = typer.Argument(..., help="Reflect manifest JSON path to validate.")) -> None:
    """Validate a Reflector manifest."""

    issues = validate_reflection(load_reflection(reflection))
    console.print(f"Reflect validation: {'ok' if not issues else 'blocked'}")
    for issue in issues:
        console.print(f"Issue: {issue}")
    if issues:
        raise typer.Exit(1)


@ratchet_app.command("apply")
def ratchet_apply_cmd(
    reflection: Optional[Path] = typer.Option(None, "--reflection", help="Reflect manifest; defaults to .vibe/kernel/reflect_manifest.json."),
    execution_manifest: Optional[Path] = typer.Option(None, "--execution-manifest"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Apply layered belief updates from a Reflector manifest."""

    paths_ = paths(target)
    paths_.require_initialized()
    record = apply_belief_ratchet(paths_, reflection_path=reflection, execution_manifest=execution_manifest)
    console.print(f"Ratchet evidence type: {record.get('evidence_type', '')}")
    console.print(f"Ratchet record: {paths_.kernel / 'belief_ratchet_record.json'}")
    if record.get("validation_issues"):
        for issue in record["validation_issues"]:
            console.print(f"Issue: {issue}")
        raise typer.Exit(1)


@ratchet_app.command("validate")
def ratchet_validate_cmd(record: Path = typer.Argument(..., help="Belief ratchet record JSON path.")) -> None:
    """Validate a Belief Ratchet record."""

    issues = validate_ratchet_record(load_ratchet_record(record))
    console.print(f"Ratchet validation: {'ok' if not issues else 'blocked'}")
    for issue in issues:
        console.print(f"Issue: {issue}")
    if issues:
        raise typer.Exit(1)


@registry_app.command("record")
def registry_record_cmd(
    event_type: str = typer.Option(..., "--event-type"),
    payload: Path = typer.Argument(..., help="JSON payload to fingerprint and record."),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Append a fingerprinted research registry event."""

    paths_ = paths(target)
    paths_.require_initialized()
    record = record_registry_event(paths_, event_type=event_type, payload=read_json(payload, {}))
    console.print_json(data=record)


@registry_app.command("check")
def registry_check_cmd(plan: Path = typer.Argument(..., help="Draft plan or plan-like JSON."), target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Check whether a candidate route repeats immune memory."""

    paths_ = paths(target)
    paths_.require_initialized()
    result = immune_check(paths_, read_json(plan, {}))
    console.print_json(data=result)
    if result["blocked"]:
        raise typer.Exit(1)


@registry_app.command("budget-recovery")
def registry_budget_recovery_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Show budget checkpoint/resume events indexed by the registry."""

    console.print_json(data=load_budget_recovery(paths(target)))


@debt_app.command("list")
def debt_list_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Show open WATCH/REFINE decision debts."""

    paths_ = paths(target)
    paths_.require_initialized()
    console.print_json(data={"open_debts": load_open_decision_debts(paths_), "state": load_debt_state(paths_)})


@debt_app.command("validate")
def debt_validate_cmd(record: Path = typer.Argument(..., help="Decision debt record JSON path.")) -> None:
    """Validate a structured decision debt record."""

    issues = validate_debt_record(read_json(record, {}))
    console.print(f"Debt validation: {'ok' if not issues else 'blocked'}")
    for issue in issues:
        console.print(f"Issue: {issue}")
    if issues:
        raise typer.Exit(1)


@debt_app.command("clear")
def debt_clear_cmd(rounds: int = typer.Option(1, "--rounds", min=1), target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Advance debt TTL and clear expired debts into STOP or PIVOT."""

    paths_ = paths(target)
    paths_.require_initialized()
    result = clear_expired_decision_debts(paths_, rounds=rounds)
    console.print_json(data=result)


@knowledge_app.command("ingest")
def knowledge_ingest_cmd(
    source_type: str = typer.Option(..., "--source-type"),
    source: str = typer.Option(..., "--source"),
    status: str = typer.Option("INGESTED", "--status"),
    card_id: str = typer.Option("", "--card-id"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Record a lifecycle event for repo/paper/deep-note/user-idea knowledge."""

    paths_ = paths(target)
    paths_.require_initialized()
    try:
        record = record_knowledge_event(paths_, source_type=source_type, source=source, status=status, card_id=card_id)
    except ValueError as exc:
        console.print(str(exc))
        raise typer.Exit(1) from exc
    console.print_json(data=record)


@knowledge_app.command("advance-ttl")
def knowledge_advance_ttl_cmd(cycles: int = typer.Option(1, "--cycles", min=1), target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Advance active knowledge TTL and expire unresolved orphans."""

    paths_ = paths(target)
    paths_.require_initialized()
    console.print_json(data=advance_knowledge_ttl(paths_, cycles=cycles))


@knowledge_app.command("audit")
def knowledge_audit_cmd(refresh: bool = typer.Option(True, "--refresh/--cached"), target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Report active, archived, negative, and expired knowledge counts."""

    paths_ = paths(target)
    paths_.require_initialized()
    console.print_json(data=orphan_audit(paths_) if refresh else load_orphan_audit(paths_))


@os_beta_app.command("run")
def os_beta_run_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Run the generic closed-loop OS beta harness."""

    paths_ = paths(target)
    paths_.require_initialized()
    result = run_closed_loop_harness(paths_)
    console.print_json(data=result)
    if not result.get("chain_complete"):
        raise typer.Exit(1)


@os_beta_app.command("validate")
def os_beta_validate_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Validate closed-loop OS beta harness artifacts."""

    paths_ = paths(target)
    paths_.require_initialized()
    result = validate_closed_loop(paths_)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


@anti_stall_app.command("run")
def anti_stall_run_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Run anti-stall benchmark traps against the framework gates."""

    paths_ = paths(target)
    paths_.require_initialized()
    result = run_anti_stall_benchmark(paths_)
    console.print_json(data=result)
    if validate_anti_stall_report(result):
        raise typer.Exit(1)


@anti_stall_app.command("validate")
def anti_stall_validate_cmd(report: Optional[Path] = typer.Argument(None), target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Validate an anti-stall benchmark report."""

    paths_ = paths(target)
    paths_.require_initialized()
    data = read_json(report or (paths_.kernel / "ANTI_STALL_BENCHMARK.json"), {})
    issues = validate_anti_stall_report(data)
    console.print(f"Anti-stall validation: {'ok' if not issues else 'blocked'}")
    for issue in issues:
        console.print(f"Issue: {issue}")
    if issues:
        raise typer.Exit(1)


@kernel_app.command("status")
def kernel_status_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Show whether a new session can recover shared kernel state."""

    paths_ = paths(target)
    paths_.require_initialized()
    status_ = kernel_status(paths_)
    console.print(f"Kernel: {status_['kernel_dir']}")
    console.print(f"Status: {'ok' if status_['ok'] else 'missing_required_files'}")
    console.print(f"Evidence records: {status_['evidence_count']}")
    if status_["missing_files"]:
        console.print("Missing: " + ", ".join(status_["missing_files"]))
        raise typer.Exit(1)


@kernel_app.command("roles")
def kernel_roles_cmd() -> None:
    """List session roles and their writable protocol surfaces."""

    table = Table("Role", "Type", "Writable Files", "Forbidden Actions")
    for role in SESSION_ROLES.values():
        table.add_row(role.name, role.role_type, ", ".join(role.writable_files), ", ".join(role.forbidden_actions))
    console.print(table)


@kernel_app.command("check-role")
def kernel_check_role_cmd(
    session_role: str = typer.Option(..., "--session-role"),
    action: str = typer.Option(..., "--action"),
    output: str = typer.Option("", "--output"),
    budget_checked: bool = typer.Option(False, "--budget-checked"),
    quota_percent: Optional[float] = typer.Option(None, "--quota-percent"),
) -> None:
    """Validate a session role action before it mutates files or runs work."""

    result = check_role_permission(
        session_role=session_role,
        action=action,
        output_path=output,
        budget_checked=budget_checked,
        quota_percent=quota_percent,
    )
    console.print(f"Role permission: {'ok' if result.ok else 'blocked'}")
    console.print(f"Role: {result.session_role}")
    console.print(f"Action: {result.action}")
    if result.allowed_outputs:
        console.print("Allowed outputs: " + ", ".join(result.allowed_outputs))
    for reason in result.reasons:
        console.print(f"Reason: {reason}")
    if not result.ok:
        raise typer.Exit(1)


@kernel_app.command("record-evidence")
def kernel_record_evidence_cmd(
    session_role: str = typer.Option(..., "--session-role"),
    source: str = typer.Option(..., "--source"),
    artifact: str = typer.Option(..., "--artifact"),
    evidence_type: str = typer.Option(..., "--evidence-type"),
    belief_update: str = typer.Option(..., "--belief-update"),
    next_action: str = typer.Option(..., "--next-action"),
    session_id: str = typer.Option("", "--session-id"),
    target_id: str = typer.Option("", "--target-id"),
    action: str = typer.Option("", "--action"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Append an auditable evidence record to the kernel ledger."""

    paths_ = paths(target)
    paths_.require_initialized()
    try:
        record = record_evidence(
            paths_,
            session_role=session_role,
            source=source,
            artifact=artifact,
            evidence_type=evidence_type,
            belief_update=belief_update,
            next_action=next_action,
            session_id=session_id,
            target_id=target_id,
            action=action,
        )
    except ValueError as exc:
        console.print(f"Kernel evidence rejected: {exc}")
        raise typer.Exit(1) from exc
    console.print(f"Evidence recorded: {record['created_at']}")


@kernel_app.command("check-protocol")
def kernel_check_protocol_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    session_id: str = typer.Option("", "--session-id"),
    target_id: str = typer.Option("", "--target-id"),
    action: str = typer.Option("", "--action"),
) -> None:
    """Check required kernel files and closed-loop role-boundary violations."""

    paths_ = paths(target)
    paths_.require_initialized()
    result = kernel_check_protocol(paths_, proposed_session_id=session_id, proposed_target_id=target_id, proposed_action=action)
    console.print(f"Protocol: {'ok' if result.ok else 'blocked'}")
    console.print(f"Evidence records: {result.evidence_count}")
    if result.missing_files:
        console.print("Missing: " + ", ".join(result.missing_files))
    for violation in result.violations:
        console.print(f"Violation: {violation}")
    if not result.ok:
        raise typer.Exit(1)


@planner_app.command("draft")
def planner_draft_cmd(
    mode: str = typer.Option(..., "--mode", help="Generation mode: exploit, recombine, or invent."),
    failure_anchor: str = typer.Option(..., "--failure-anchor"),
    hypothesis: str = typer.Option(..., "--hypothesis"),
    mechanism: str = typer.Option(..., "--mechanism"),
    minimum_experiment: str = typer.Option(..., "--minimum-experiment"),
    expected_artifact: str = typer.Option(..., "--expected-artifact"),
    expected_belief_update: str = typer.Option(..., "--expected-belief-update"),
    compute_cost: str = typer.Option(..., "--compute-cost"),
    risk: str = typer.Option(..., "--risk"),
    fallback: str = typer.Option(..., "--fallback"),
    stop_condition: str = typer.Option(..., "--stop-condition"),
    confidence: str = typer.Option("speculative_mechanism", "--confidence"),
    output: str = typer.Option("draft_plan_manifest.json", "--output"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Write a Planner-only draft plan manifest for later review."""

    paths_ = paths(target)
    paths_.require_initialized()
    plan = build_draft_plan(
        paths_,
        mode=mode,
        failure_anchor=failure_anchor,
        hypothesis=hypothesis,
        mechanism=mechanism,
        minimum_experiment=minimum_experiment,
        expected_artifact=expected_artifact,
        expected_belief_update=expected_belief_update,
        compute_cost=compute_cost,
        risk=risk,
        fallback=fallback,
        stop_condition=stop_condition,
        confidence=confidence,
    )
    ok, diagnostics = validate_draft_plan(plan)
    path = write_draft_plan(paths_, plan, output=output)
    console.print(f"Draft plan: {path}")
    console.print(f"Review route: {plan['review_route']}")
    for item in diagnostics:
        console.print(f"{item['level']}: {item['code']} - {item['message']}")
    if not ok:
        raise typer.Exit(1)


@planner_app.command("validate")
def planner_validate_cmd(plan: Path = typer.Argument(..., help="Draft plan JSON path to validate.")) -> None:
    """Validate a draft plan manifest without approving or executing it."""

    draft = load_draft_plan(plan)
    ok, diagnostics = validate_draft_plan(draft)
    console.print(f"Draft plan validation: {'ok' if ok else 'blocked'}")
    for item in diagnostics:
        console.print(f"{item['level']}: {item['code']} - {item['message']}")
    if not ok:
        raise typer.Exit(1)


@planner_app.command("draft-from-card")
def planner_draft_from_card_cmd(
    card: str = typer.Argument(..., help="Mechanism card id or JSON sidecar path."),
    confidence: str = typer.Option("speculative_mechanism", "--confidence"),
    output: str = typer.Option("draft_plan_manifest.json", "--output"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Create a Planner draft from a validated mechanism card."""

    paths_ = paths(target)
    paths_.require_initialized()
    try:
        draft = build_draft_from_mechanism_card(paths_, load_mechanism_card(paths_, card), confidence=confidence)
    except ValueError as exc:
        console.print(str(exc))
        raise typer.Exit(1) from exc
    ok, diagnostics = validate_draft_plan(draft)
    path = write_draft_plan(paths_, draft, output=output)
    console.print(f"Draft plan: {path}")
    console.print(f"Review route: {draft['review_route']}")
    for item in diagnostics:
        console.print(f"{item['level']}: {item['code']} - {item['message']}")
    if not ok:
        raise typer.Exit(1)


@planner_app.command("resubmit")
def planner_resubmit_cmd(
    revision_packet: Path = typer.Option(..., "--revision-packet"),
    draft: Optional[Path] = typer.Option(None, "--draft"),
    set_field: list[str] = typer.Option([], "--set", help="Allowed field update as field=value; may repeat."),
    addressed: list[str] = typer.Option([], "--addressed"),
    not_addressed: list[str] = typer.Option([], "--not-addressed"),
    output: str = typer.Option("draft_plan_manifest.json", "--output"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Resubmit a Planner draft by changing only fields requested by Reviewer."""

    paths_ = paths(target)
    paths_.require_initialized()
    draft_path = draft or (paths_.kernel / "draft_plan_manifest.json")
    updates: dict[str, str] = {}
    for item in set_field:
        field, sep, value = item.partition("=")
        if not sep or not field.strip():
            raise typer.BadParameter("--set must use field=value")
        updates[field.strip()] = value
    try:
        revised = resubmit_draft(load_draft_plan(draft_path), load_revision_packet(revision_packet), updates, addressed=addressed, not_addressed=not_addressed)
    except ValueError as exc:
        console.print(f"Resubmission rejected: {exc}")
        raise typer.Exit(1) from exc
    path = write_resubmitted_draft(paths_, revised, output=output)
    console.print(f"Resubmitted draft: {path}")


@reviewer_app.command("review")
def reviewer_review_cmd(
    draft: Optional[Path] = typer.Option(None, "--draft", help="Draft plan JSON path; defaults to .vibe/kernel/draft_plan_manifest.json."),
    report_output: str = typer.Option("plan_review_report.md", "--report-output"),
    reviewed_output: str = typer.Option("reviewed_plan_manifest.json", "--reviewed-output"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Review a Planner draft and write report plus accepted manifest only."""

    paths_ = paths(target)
    paths_.require_initialized()
    draft_path = draft or (paths_.kernel / "draft_plan_manifest.json")
    review = review_draft_file(paths_, draft_path)
    outputs = write_review_outputs(paths_, review, report_name=report_output, reviewed_name=reviewed_output)
    console.print(f"Verdict: {review['verdict']}")
    console.print(f"Report: {outputs['report']}")
    if outputs["reviewed_manifest"]:
        console.print(f"Reviewed manifest: {outputs['reviewed_manifest']}")
    if review["verdict"] != "ACCEPT":
        raise typer.Exit(1)


@reviewer_app.command("revision-packet")
def reviewer_revision_packet_cmd(
    draft: Optional[Path] = typer.Option(None, "--draft"),
    output: str = typer.Option("revision_packet.json", "--output"),
    max_rounds: int = typer.Option(2, "--max-rounds"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Create a structured revision packet from the current review result."""

    paths_ = paths(target)
    paths_.require_initialized()
    draft_path = draft or (paths_.kernel / "draft_plan_manifest.json")
    review = review_draft_file(paths_, draft_path)
    packet = build_revision_packet(review, max_rounds=max_rounds)
    path = write_revision_packet(paths_, packet, output=output)
    console.print(f"Revision packet: {path}")
    console.print(f"Verdict: {packet['verdict']}")
    if packet["verdict"] != "REVISE":
        raise typer.Exit(1)


@reviewer_app.command("validate")
def reviewer_validate_cmd(review_json: Path = typer.Argument(..., help="Review JSON path to validate.")) -> None:
    """Validate a structured review JSON without executing it."""

    review = read_json(review_json, {})
    verdict = review.get("verdict", "")
    console.print(f"Review validation: {'ok' if verdict in {'ACCEPT', 'REVISE', 'REJECT', 'ASK_HUMAN'} else 'blocked'}")
    console.print(f"Verdict: {verdict}")
    if verdict not in {"ACCEPT", "REVISE", "REJECT", "ASK_HUMAN"}:
        raise typer.Exit(1)


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


@research_app.command("sustained-audit")
def research_sustained_audit_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    target_rounds: int = typer.Option(3, "--target-rounds"),
    min_routes: int = typer.Option(3, "--min-routes"),
) -> None:
    """Audit multi-route, reflected, externally informed sustained rounds."""

    result = sustained_round_audit(paths(target), target_rounds=target_rounds, min_routes_per_round=min_routes)
    console.print_json(data=result)


@research_app.command("sustained-selftest")
def research_sustained_selftest_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Run an isolated synthetic sustained-round contract self-test."""

    result = sustained_round_selftest(paths(target))
    console.print_json(data=result)
    if result.get("status") != "passed":
        raise typer.Exit(1)


@research_app.command("sustained-next")
def research_sustained_next_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    offline: bool = typer.Option(False, "--offline"),
    dry_submit: bool = typer.Option(False, "--dry-submit", help="Record backend submissions without launching jobs."),
    real_submit: bool = typer.Option(False, "--real-submit", help="Explicitly allow real backend submission."),
) -> None:
    """Execute one sustained research step with fail-closed submission semantics."""

    console.print(run_auto_next(paths(target), offline=offline, dry_submit=effective_dry_submit(dry_submit, real_submit)))


@research_app.command("sustained-cycle")
def research_sustained_cycle_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    offline: bool = typer.Option(False, "--offline"),
    dry_submit: bool = typer.Option(False, "--dry-submit", help="Record backend submissions without launching jobs."),
    real_submit: bool = typer.Option(False, "--real-submit", help="Explicitly allow real backend submission."),
    max_steps: int = typer.Option(30, "--max-steps"),
) -> None:
    """Advance sustained research until submit/manual/block with dry submission by default."""

    for line in run_auto_cycle(paths(target), offline=offline, dry_submit=effective_dry_submit(dry_submit, real_submit), max_steps=max_steps):
        console.print(line)


@research_app.command("answer")
def research_answer_cmd(
    question_id: str = typer.Argument(...),
    answer: str = typer.Option(..., "--answer"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    confirm: bool = typer.Option(True, "--confirm/--no-confirm"),
) -> None:
    """Record a user answer for an initialization or research policy question."""

    p = paths(target)
    row = answer_research_question(p, question_id, answer, confirm=confirm)
    sync_dashboard(p)
    console.print_json(data=row)


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


@mve_app.command("validate")
def mve_validate_cmd(
    manifest: Path = typer.Argument(..., help="Execution manifest JSON path."),
    check_artifact: bool = typer.Option(False, "--check-artifact"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Validate MVE contract fields and optionally require the artifact."""

    data = load_mve_manifest(manifest)
    issues = validate_mve_completion(paths(target).root, data) if check_artifact else validate_mve_contract(data)
    console.print(f"MVE validation: {'ok' if not issues else 'blocked'}")
    for issue in issues:
        console.print(f"Issue: {issue}")
    if issues:
        raise typer.Exit(1)


@mve_app.command("promote-success")
def mve_promote_success_cmd(
    manifest: Path = typer.Argument(..., help="Execution manifest JSON path."),
    output: str = typer.Option(".vibe/kernel/mve_promotion_debt.json", "--output"),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Record the next evidence debt after MVE success."""

    output_path = paths(target).root / output
    write_promotion_debt(output_path, promotion_debt_for_success(load_mve_manifest(manifest)))
    console.print(f"MVE promotion debt: {output_path}")


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


@portfolio_app.command("track-plan")
def portfolio_track_plan_cmd(
    experiment_id: str = typer.Argument(...),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    track: str = typer.Option(..., "--track"),
    internalization_level: str = typer.Option("external_only", "--internalization-level"),
    external_baseline_asset_id: str = typer.Option("", "--external-baseline-asset-id"),
    metrics_comparable: bool = typer.Option(False, "--metrics-comparable"),
    design_diff: list[str] = typer.Option([], "--design-diff"),
    protected_metric_passed: bool = typer.Option(True, "--protected-metric-passed/--protected-metric-failed"),
    trusted_evidence_id: list[str] = typer.Option([], "--trusted-evidence-id"),
    gpu_hours: float = typer.Option(0.0, "--gpu-hours"),
    pseudo_internalization: bool = typer.Option(False, "--pseudo-internalization"),
    pseudo_internalization_reason: str = typer.Option("", "--pseudo-internalization-reason"),
) -> None:
    """Attach external/internal/hybrid track metadata to an experiment."""

    result = create_track_experiment(
        paths(target),
        experiment_id=experiment_id,
        track=track,
        internalization_level=internalization_level,
        external_baseline_asset_id=external_baseline_asset_id,
        metrics_comparable=metrics_comparable,
        design_diff={"changes": design_diff} if design_diff else {},
        protected_metric_gate={"passed": protected_metric_passed},
        trusted_evidence_ids=trusted_evidence_id,
        resource_units={"gpu_hours": gpu_hours},
        pseudo_internalization=pseudo_internalization,
        pseudo_internalization_reason=pseudo_internalization_reason,
    )
    console.print_json(data=result)


@portfolio_app.command("compare-plan")
def portfolio_compare_plan_cmd(
    track_record_id: str = typer.Argument(...),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    comparison_stage: str = typer.Option("smoke", "--comparison-stage"),
) -> None:
    """Create a parallel comparison plan against the external baseline."""

    result = parallel_comparison_plan(paths(target), track_record_id, comparison_stage=comparison_stage)
    console.print_json(data=result)
    if result.get("blocked"):
        raise typer.Exit(1)


@portfolio_app.command("track-audit")
def portfolio_track_audit_cmd(
    track_record_id: str = typer.Argument(...),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    target_level: str = typer.Option("shadow_internal", "--target-level"),
) -> None:
    """Audit dual-track transition readiness for an experiment."""

    result = track_transition_audit(paths(target), track_record_id, target_level=target_level)
    console.print_json(data=result)
    if not result.get("can_transition"):
        raise typer.Exit(1)


@portfolio_app.command("track-budget")
def portfolio_track_budget_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Audit configured budget ratios by track."""

    console.print_json(data=track_budget_audit(paths(target)))


@portfolio_app.command("track-memo")
def portfolio_track_memo_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Render daily dual-track portfolio status."""

    console.print_json(data=track_memo(paths(target)))


@external_app.command("clone-repo")
def external_clone_repo_cmd(
    url: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    name: str = typer.Option("", "--name"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Clone an external method repository into `.vibe/research/external_repos`."""

    result = clone_external_repo(paths(target), url, name=name, dry_run=dry_run)
    console.print_json(data=result)
    if result.get("status") == "failed":
        raise typer.Exit(1)


@external_app.command("analyze-repo")
def external_analyze_repo_cmd(name: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Create a read-only integration analysis for a cloned external repo."""

    result = analyze_external_repo(paths(target), name)
    console.print_json(data=result)


@lineage_app.command("add-external-asset")
def lineage_add_external_asset_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    source: str = typer.Option(..., "--source"),
    title: str = typer.Option("", "--title"),
    asset_type: str = typer.Option("external_repo", "--asset-type"),
    purpose: str = typer.Option("reference_implementation", "--purpose"),
    credibility: str = typer.Option("unknown", "--credibility"),
    license_or_restrictions: str = typer.Option("", "--license"),
    dependency_mode: str = typer.Option("unknown", "--dependency-mode"),
    replacement_plan: str = typer.Option("", "--replacement-plan"),
) -> None:
    """Register an external asset with purpose, restrictions, and dependency mode."""

    result = add_external_asset(
        paths(target),
        source=source,
        title=title,
        asset_type=asset_type,
        purpose=purpose,
        credibility=credibility,
        license_or_restrictions=license_or_restrictions,
        dependency_mode=dependency_mode,
        replacement_plan=replacement_plan,
    )
    console.print_json(data=result)


@lineage_app.command("link")
def lineage_link_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    source_id: str = typer.Option(..., "--source-id"),
    target_id: str = typer.Option(..., "--target-id"),
    relation_type: str = typer.Option(..., "--relation-type"),
    rationale: str = typer.Option("", "--rationale"),
) -> None:
    """Create a generic lineage relation between assets, ideas, proposals, and evidence."""

    console.print_json(data=add_lineage_relation(paths(target), source_id=source_id, target_id=target_id, relation_type=relation_type, rationale=rationale))


@internalization_app.command("decision")
def internalization_decision_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    internalize_what: str = typer.Option(..., "--internalize-what"),
    why_now: str = typer.Option(..., "--why-now"),
    expected_benefit: str = typer.Option(..., "--expected-benefit"),
    downstream_src_target: str = typer.Option(..., "--downstream-src-target"),
    baseline_comparison: str = typer.Option(..., "--baseline-comparison"),
    rollback_plan: str = typer.Option(..., "--rollback-plan"),
    proposal_id: str = typer.Option("", "--proposal-id"),
    hypothesis_id: str = typer.Option("", "--hypothesis-id"),
    asset_id: str = typer.Option("", "--asset-id"),
    risk: list[str] = typer.Option([], "--risk"),
    new_script: list[str] = typer.Option([], "--new-script"),
    adapter_capability_impact: str = typer.Option("", "--adapter-capability-impact"),
    evidence_id: list[str] = typer.Option([], "--evidence-id"),
    status: str = typer.Option("proposed", "--status"),
) -> None:
    """Record a structured internalization decision argument."""

    result = record_internalization_decision(
        paths(target),
        internalize_what=internalize_what,
        why_now=why_now,
        expected_benefit=expected_benefit,
        downstream_src_target=downstream_src_target,
        baseline_comparison=baseline_comparison,
        rollback_plan=rollback_plan,
        proposal_id=proposal_id,
        hypothesis_id=hypothesis_id,
        asset_id=asset_id,
        risks=risk,
        new_scripts_needed=new_script,
        adapter_capability_impact=adapter_capability_impact,
        evidence_ids=evidence_id,
        status=status,
    )
    console.print_json(data=result)


@internalization_app.command("propose")
def internalization_propose_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    title: str = typer.Option(..., "--title"),
    hypothesis_id: str = typer.Option(..., "--hypothesis-id"),
    asset_id: str = typer.Option(..., "--asset-id"),
    design_summary: str = typer.Option(..., "--design-summary"),
    module_design: str = typer.Option(..., "--module-design"),
    data_flow: str = typer.Option(..., "--data-flow"),
    metrics_schema_ref: str = typer.Option(..., "--metrics-schema-ref"),
    external_baseline_asset_id: str = typer.Option(..., "--external-baseline-asset-id"),
    rollback_strategy: str = typer.Option(..., "--rollback-strategy"),
    minimal_scope: str = typer.Option(..., "--minimal-scope"),
    downstream_src_target: str = typer.Option(..., "--downstream-src-target"),
    remaining_upside: str = typer.Option(..., "--remaining-upside"),
    interface: list[str] = typer.Option([], "--interface"),
    training_entrypoint: str = typer.Option("", "--training-entrypoint"),
    evaluation_entrypoint: str = typer.Option("", "--evaluation-entrypoint"),
    expected_ablation: list[str] = typer.Option([], "--expected-ablation"),
    trusted_evidence_id: list[str] = typer.Option([], "--trusted-evidence-id"),
    scout_evidence_id: list[str] = typer.Option([], "--scout-evidence-id"),
    status: str = typer.Option("proposed", "--status"),
) -> None:
    """Create a framework proposal for review before any owned implementation."""

    result = create_framework_proposal(
        paths(target),
        title=title,
        hypothesis_id=hypothesis_id,
        asset_id=asset_id,
        design_summary=design_summary,
        module_design=module_design,
        data_flow=data_flow,
        metrics_schema_ref=metrics_schema_ref,
        external_baseline_asset_id=external_baseline_asset_id,
        rollback_strategy=rollback_strategy,
        minimal_scope=minimal_scope,
        downstream_src_target=downstream_src_target,
        remaining_upside=remaining_upside,
        interfaces=interface,
        training_entrypoint=training_entrypoint,
        evaluation_entrypoint=evaluation_entrypoint,
        expected_ablations=expected_ablation,
        trusted_evidence_ids=trusted_evidence_id,
        scout_evidence_ids=scout_evidence_id,
        status=status,
    )
    console.print_json(data=result)


@internalization_app.command("readiness")
def internalization_readiness_cmd(
    proposal_id: str = typer.Argument(...),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    target_level: str = typer.Option("shadow_internal", "--target-level"),
) -> None:
    """Evaluate whether a framework proposal can move to the requested internalization level."""

    result = internalization_readiness(paths(target), proposal_id, target_level=target_level)
    console.print_json(data=result)
    if not result.get("can_transition"):
        raise typer.Exit(1)


@internalization_app.command("memory")
def internalization_memory_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Render lineage-aware planning memory for future agent context."""

    console.print_json(data=build_lineage_memory(paths(target)))


@scout_app.command("query-context")
def scout_query_context_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Build traceable scout query context from research memory and hypotheses."""

    console.print_json(data=scout_query_context(paths(target)))


@scout_app.command("add-finding")
def scout_add_finding_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    title: str = typer.Option(..., "--title"),
    source_type: str = typer.Option("paper", "--source-type"),
    authors_or_repo: str = typer.Option("", "--authors-or-repo"),
    year: str = typer.Option("", "--year"),
    url_or_ref: str = typer.Option("", "--url-or-ref"),
    task_match: float = typer.Option(0.0, "--task-match"),
    dataset_match: float = typer.Option(0.0, "--dataset-match"),
    metric_match: float = typer.Option(0.0, "--metric-match"),
    method_match: float = typer.Option(0.0, "--method-match"),
    failure_mode_match: float = typer.Option(0.0, "--failure-mode-match"),
    actionability: float = typer.Option(0.0, "--actionability"),
    novelty: float = typer.Option(0.0, "--novelty"),
    credibility: float = typer.Option(0.0, "--credibility"),
    has_code: bool = typer.Option(False, "--has-code"),
    reproducible_experiment: bool = typer.Option(False, "--reproducible-experiment"),
    hypothesis_id: str = typer.Option("", "--hypothesis-id"),
    relationship_to_hypothesis: str = typer.Option("", "--relationship"),
    possible_experiment: str = typer.Option("", "--possible-experiment"),
    risk: list[str] = typer.Option([], "--risk"),
    counterevidence: list[str] = typer.Option([], "--counterevidence"),
    confidence: float = typer.Option(0.0, "--confidence"),
    summary: str = typer.Option("", "--summary"),
) -> None:
    """Record a scout finding with structured quality scores."""

    console.print_json(
        data=add_scout_finding(
            paths(target),
            title=title,
            source_type=source_type,
            authors_or_repo=authors_or_repo,
            year=year,
            url_or_ref=url_or_ref,
            task_match=task_match,
            dataset_match=dataset_match,
            metric_match=metric_match,
            method_match=method_match,
            failure_mode_match=failure_mode_match,
            actionability=actionability,
            novelty=novelty,
            credibility=credibility,
            has_code=has_code,
            reproducible_experiment=reproducible_experiment,
            hypothesis_id=hypothesis_id,
            relationship_to_hypothesis=relationship_to_hypothesis,
            possible_experiment=possible_experiment,
            risks=risk,
            counterevidence=counterevidence,
            confidence=confidence,
            summary=summary,
        )
    )


@scout_app.command("triage")
def scout_triage_cmd(
    finding_id: str = typer.Argument(...),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    rationale: str = typer.Option("", "--rationale"),
) -> None:
    """Classify a scout finding through the quality gate."""

    console.print_json(data=triage_scout_finding(paths(target), finding_id, rationale=rationale))


@scout_app.command("claim")
def scout_claim_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    claim: str = typer.Option(..., "--claim"),
    support_finding_id: list[str] = typer.Option([], "--support-finding-id"),
    oppose_finding_id: list[str] = typer.Option([], "--oppose-finding-id"),
    applicability: str = typer.Option("", "--applicability"),
    transfer_limits: str = typer.Option("", "--transfer-limits"),
    suggested_experiment: str = typer.Option("", "--suggested-experiment"),
    confidence: float = typer.Option(0.0, "--confidence"),
) -> None:
    """Create a claim-evidence map entry from triaged scout findings."""

    console.print_json(
        data=create_scout_claim(
            paths(target),
            claim=claim,
            support_finding_ids=support_finding_id,
            oppose_finding_ids=oppose_finding_id,
            applicability=applicability,
            transfer_limits=transfer_limits,
            suggested_experiment=suggested_experiment,
            confidence=confidence,
        )
    )


@scout_app.command("mechanism-card")
def scout_mechanism_card_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    source: str = typer.Option(..., "--source"),
    claim: str = typer.Option(..., "--claim"),
    mechanism_extraction: str = typer.Option(..., "--mechanism-extraction"),
    why_it_matters: str = typer.Option(..., "--why-it-matters"),
    failure_anchor: str = typer.Option(..., "--failure-anchor"),
    possible_mve: str = typer.Option("", "--possible-mve"),
    required_asset: list[str] = typer.Option([], "--required-asset"),
    risk: list[str] = typer.Option([], "--risk"),
    stop_reason: str = typer.Option(..., "--stop-reason"),
    source_type: str = typer.Option("paper", "--source-type"),
) -> None:
    """Write a Scout mechanism_card.md without creating execution manifests."""

    paths_ = paths(target)
    paths_.require_initialized()
    card = create_mechanism_card(
        paths_,
        source=source,
        claim=claim,
        mechanism_extraction=mechanism_extraction,
        why_it_matters=why_it_matters,
        failure_anchor=failure_anchor,
        possible_mve=possible_mve,
        required_assets=required_asset,
        risks=risk,
        stop_reason=stop_reason,
        source_type=source_type,
    )
    console.print_json(data=card)


@scout_app.command("validate-card")
def scout_validate_card_cmd(card: str = typer.Argument(...), target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Validate a mechanism card before Planner consumes it."""

    paths_ = paths(target)
    paths_.require_initialized()
    issues = validate_mechanism_card(load_mechanism_card(paths_, card))
    console.print(f"Mechanism card validation: {'ok' if not issues else 'blocked'}")
    for issue in issues:
        console.print(f"Issue: {issue}")
    if issues:
        raise typer.Exit(1)


@scout_app.command("audit")
def scout_audit_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Summarize scout quality, actionable evidence, claims, and negative evidence."""

    console.print_json(data=scout_audit(paths(target)))


@owned_app.command("scaffold")
def owned_scaffold_cmd(
    proposal_id: str = typer.Argument(...),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    framework_name: str = typer.Option("", "--framework-name"),
    allow_overwrite: bool = typer.Option(False, "--allow-overwrite"),
) -> None:
    """Generate a downstream owned-framework alpha scaffold from an approved proposal."""

    result = scaffold_owned_framework(paths(target), proposal_id, framework_name=framework_name, allow_overwrite=allow_overwrite)
    console.print_json(data=result)
    if result.get("status") != "created":
        raise typer.Exit(1)


@owned_app.command("contract")
def owned_contract_cmd(
    framework_name: str = typer.Argument(...),
    target: Path = typer.Option(Path("."), "--target", "-t"),
) -> None:
    """Run owned-framework alpha contract checks."""

    result = owned_contract(paths(target), framework_name)
    console.print_json(data=result)
    if not result.get("passed"):
        raise typer.Exit(1)


@owned_app.command("shadow-plan")
def owned_shadow_plan_cmd(
    proposal_id: str = typer.Argument(...),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    sample_scope: str = typer.Option("small_sample", "--sample-scope"),
) -> None:
    """Create a shadow execution plan that keeps the external baseline."""

    console.print_json(data=owned_shadow_plan(paths(target), proposal_id, sample_scope=sample_scope))


@owned_app.command("audit")
def owned_audit_cmd(
    framework_name: str = typer.Argument(...),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    proposal_id: str = typer.Option("", "--proposal-id"),
) -> None:
    """Audit owned code against proposal, dependency, schema, and external-call rules."""

    result = owned_design_audit(paths(target), framework_name, proposal_id=proposal_id)
    console.print_json(data=result)
    if not result.get("owned_core_allowed"):
        raise typer.Exit(1)


@optimize_app.command("champion")
def optimize_champion_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    stage: str = typer.Option(..., "--stage"),
    candidate_id: str = typer.Option(..., "--candidate-id"),
    candidate_type: str = typer.Option("owned", "--candidate-type"),
    evidence_id: list[str] = typer.Option([], "--evidence-id"),
    protected_metric_passed: bool = typer.Option(True, "--protected-metric-passed/--protected-metric-failed"),
    budget_policy_ok: bool = typer.Option(False, "--budget-policy-ok"),
    rationale: str = typer.Option("", "--rationale"),
) -> None:
    """Promote a candidate to champion only when evidence and policy gates pass."""

    result = promote_champion(paths(target), stage=stage, candidate_id=candidate_id, candidate_type=candidate_type, evidence_ids=evidence_id, protected_metric_gate={"passed": protected_metric_passed}, budget_policy_ok=budget_policy_ok, rationale=rationale)
    console.print_json(data=result)
    if not result.get("promoted"):
        raise typer.Exit(1)


@optimize_app.command("challenger")
def optimize_challenger_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    stage: str = typer.Option(..., "--stage"),
    candidate_id: str = typer.Option(..., "--candidate-id"),
    candidate_type: str = typer.Option("owned", "--candidate-type"),
    against_champion_id: str = typer.Option("", "--against-champion-id"),
    rationale: str = typer.Option("", "--rationale"),
) -> None:
    """Register a challenger against the current champion."""

    console.print_json(data=register_challenger(paths(target), stage=stage, candidate_id=candidate_id, candidate_type=candidate_type, against_champion_id=against_champion_id, rationale=rationale))


@optimize_app.command("ablation")
def optimize_ablation_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    candidate_id: str = typer.Option(..., "--candidate-id"),
    ablation_key: str = typer.Option(..., "--ablation-key"),
    hypothesis: str = typer.Option(..., "--hypothesis"),
    expected_effect: str = typer.Option(..., "--expected-effect"),
    metrics_target: str = typer.Option(..., "--metrics-target"),
    protected_metric_risk: str = typer.Option(..., "--protected-metric-risk"),
    rollback_plan: str = typer.Option(..., "--rollback-plan"),
) -> None:
    """Plan a structured owned-framework ablation."""

    console.print_json(data=plan_ablation(paths(target), candidate_id=candidate_id, ablation_key=ablation_key, hypothesis=hypothesis, expected_effect=expected_effect, metrics_target=metrics_target, protected_metric_risk=protected_metric_risk, rollback_plan=rollback_plan))


@optimize_app.command("regression")
def optimize_regression_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    candidate_id: str = typer.Option(..., "--candidate-id"),
    stage: str = typer.Option(..., "--stage"),
    smoke: bool = typer.Option(True, "--smoke/--no-smoke"),
    metrics_schema: bool = typer.Option(True, "--metrics-schema/--no-metrics-schema"),
    artifact_output: bool = typer.Option(True, "--artifact-output/--no-artifact-output"),
    protected_metrics: bool = typer.Option(True, "--protected-metrics/--no-protected-metrics"),
    champion_comparison: bool = typer.Option(True, "--champion-comparison/--no-champion-comparison"),
) -> None:
    """Record a regression suite result for an owned challenger."""

    checks = {"smoke": smoke, "metrics_schema": metrics_schema, "artifact_output": artifact_output, "protected_metrics": protected_metrics, "champion_comparison": champion_comparison}
    result = record_regression_suite(paths(target), candidate_id=candidate_id, stage=stage, checks=checks)
    console.print_json(data=result)
    if result.get("blocks_larger_stage"):
        raise typer.Exit(1)


@optimize_app.command("memory")
def optimize_memory_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    ablation_key: str = typer.Option(..., "--ablation-key"),
    outcome: str = typer.Option(..., "--outcome"),
    rationale: str = typer.Option("", "--rationale"),
) -> None:
    """Record optimization memory to prevent repeated failed ablations."""

    console.print_json(data=record_optimization_memory(paths(target), ablation_key=ablation_key, outcome=outcome, rationale=rationale))


@optimize_app.command("external-deemphasis")
def optimize_external_deemphasis_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    proposed_external_ratio: float = typer.Option(..., "--proposed-external-ratio"),
    policy_allowed: bool = typer.Option(False, "--policy-allowed"),
    rationale: str = typer.Option("", "--rationale"),
    keep_periodic_regression: bool = typer.Option(True, "--keep-periodic-regression/--drop-periodic-regression"),
) -> None:
    """Propose policy-controlled gradual external budget de-emphasis."""

    result = external_deemphasis_plan(paths(target), proposed_external_ratio=proposed_external_ratio, policy_allowed=policy_allowed, rationale=rationale, keep_periodic_regression=keep_periodic_regression)
    console.print_json(data=result)
    if not result.get("approved"):
        raise typer.Exit(1)


@present_app.command("narrative")
def present_narrative_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    claims_file: Optional[Path] = typer.Option(None, "--claims-file", help="Optional JSON list of final claims to trace."),
) -> None:
    """Build a final narrative with untraceable claims separated from evidence-backed claims."""

    claims = read_json(claims_file, []) if claims_file else None
    console.print_json(data=build_narrative(paths(target), claims=claims))


@present_app.command("reproducibility")
def present_reproducibility_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Build a reproducibility package linking conclusions to evidence, runs, code, adapter, and policy state."""

    console.print_json(data=build_reproducibility_package(paths(target)))


@present_app.command("tables")
def present_tables_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Export presentation-ready JSON tables for figures and slides."""

    result = export_presentation_tables(paths(target))
    console.print_json(data={"created_at": result["created_at"], "table_files": {key: str(value) for key, value in result["table_files"].items()}})


@present_app.command("framework-spec")
def present_framework_spec_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Build the final framework specification from lineage, owned, and adapter state."""

    console.print_json(data=build_framework_spec(paths(target)))


@present_app.command("package")
def present_package_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    claims_file: Optional[Path] = typer.Option(None, "--claims-file", help="Optional JSON list of final claims to trace."),
) -> None:
    """Build the complete presentation-ready research package."""

    claims = read_json(claims_file, []) if claims_file else None
    console.print_json(data=build_presentation_package(paths(target), claims=claims))


@converge_app.command("stage")
def converge_stage_cmd(
    stage: str = typer.Argument(...),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    rationale: str = typer.Option("", "--rationale"),
    user_approved: bool = typer.Option(False, "--user-approved"),
) -> None:
    """Set the convergence stage, enforcing freeze gates for final freeze."""

    result = set_convergence_stage(paths(target), stage, rationale=rationale, user_approved=user_approved)
    console.print_json(data=result)
    if not result.get("accepted"):
        raise typer.Exit(1)


@converge_app.command("freeze-check")
def converge_freeze_check_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    user_approved: bool = typer.Option(False, "--user-approved"),
    known_risk_review: str = typer.Option("", "--known-risk-review"),
    risk_review_file: Optional[Path] = typer.Option(None, "--risk-review-file"),
    budget_closed: bool = typer.Option(False, "--budget-closed"),
) -> None:
    """Check whether final owned freeze is allowed."""

    review = risk_review_file.read_text() if risk_review_file else known_risk_review
    result = freeze_check(paths(target), user_approved=user_approved, known_risk_review=review, budget_closed=budget_closed)
    console.print_json(data=result)
    if not result.get("accepted"):
        raise typer.Exit(1)


@converge_app.command("risk-gate")
def converge_risk_gate_cmd(
    change_type: str = typer.Argument(...),
    target: Path = typer.Option(Path("."), "--target", "-t"),
    stage: Optional[str] = typer.Option(None, "--stage"),
    protected_metric_risk: bool = typer.Option(False, "--protected-metric-risk"),
    reproducibility_risk: bool = typer.Option(False, "--reproducibility-risk"),
    core_mechanism_change: bool = typer.Option(False, "--core-mechanism-change"),
    external_method_size: str = typer.Option("none", "--external-method-size"),
    override_id: str = typer.Option("", "--override-id"),
    rationale: str = typer.Option("", "--rationale"),
) -> None:
    """Gate late-stage changes against freeze and convergence policy."""

    result = risk_gate(
        paths(target),
        change_type=change_type,
        stage=stage,
        protected_metric_risk=protected_metric_risk,
        reproducibility_risk=reproducibility_risk,
        core_mechanism_change=core_mechanism_change,
        external_method_size=external_method_size,
        override_id=override_id,
        rationale=rationale,
    )
    console.print_json(data=result)
    if result.get("decision") == "block":
        raise typer.Exit(1)


@converge_app.command("dependency-audit")
def converge_dependency_audit_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Classify external and owned dependencies for final convergence."""

    console.print_json(data=dependency_audit(paths(target)))


@converge_app.command("override")
def converge_override_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    target_name: str = typer.Option(..., "--target-name"),
    reason: str = typer.Option(..., "--reason"),
    approved_by_user: bool = typer.Option(False, "--approved-by-user"),
    scope: list[str] = typer.Option([], "--scope"),
) -> None:
    """Record a user-approved exception to a convergence gate."""

    console.print_json(data=record_override(paths(target), target=target_name, reason=reason, approved_by_user=approved_by_user, scope=scope))


@converge_app.command("close-budget")
def converge_close_budget_cmd(target: Path = typer.Option(Path("."), "--target", "-t"), rationale: str = typer.Option("", "--rationale")) -> None:
    """Record budget closure for final freeze."""

    console.print_json(data=close_convergence_budget(paths(target), rationale=rationale))


@converge_app.command("risk-review")
def converge_risk_review_cmd(target: Path = typer.Option(Path("."), "--target", "-t"), text: str = typer.Option(..., "--text")) -> None:
    """Write the known-risk review required for final freeze."""

    console.print_json(data=write_known_risk_review(paths(target), text))


@reliability_app.command("report")
def reliability_report_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    stale_hours: float = typer.Option(24.0, "--stale-hours"),
    memo_fresh_hours: float = typer.Option(24.0, "--memo-fresh-hours"),
) -> None:
    """Write a long-run reliability report without mutating live jobs."""

    console.print_json(data=reliability_report(paths(target), stale_hours=stale_hours, memo_fresh_hours=memo_fresh_hours))


@reliability_app.command("checkpoint")
def reliability_checkpoint_cmd(target: Path = typer.Option(Path("."), "--target", "-t"), label: str = typer.Option("", "--label")) -> None:
    """Append a soak checkpoint for later comparison."""

    console.print_json(data=reliability_checkpoint(paths(target), label=label))


@reliability_app.command("compare")
def reliability_compare_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    older_id: str = typer.Option("", "--older-id"),
    newer_id: str = typer.Option("", "--newer-id"),
) -> None:
    """Compare two soak checkpoints, defaulting to the latest two."""

    console.print_json(data=compare_checkpoints(paths(target), older_id=older_id, newer_id=newer_id))


@reliability_app.command("doctor")
def reliability_doctor_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    stale_hours: float = typer.Option(24.0, "--stale-hours"),
    memo_fresh_hours: float = typer.Option(24.0, "--memo-fresh-hours"),
) -> None:
    """Run reliability diagnostics and print safe operator recommendations."""

    result = reliability_doctor(paths(target), stale_hours=stale_hours, memo_fresh_hours=memo_fresh_hours)
    console.print_json(data=result)
    if result.get("status") == "blocked":
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
    if computed_block:
        console.print(f"[red]Blocked:[/red] {computed_block}")
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

    try:
        result = run_dryrun(paths(target), run_id)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
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
    lock = active_advance_lock(p)
    console.print(f"Daemon running: {daemon.get('running', False)} session={daemon.get('session', '')}")
    console.print(f"Queued={len(queue)} Active={len(active)} Completed={len(completed)} Next collect={', '.join(daemon.get('next_collection_runs', [])) or 'none'}")
    if lock:
        console.print(
            "Advance lock: "
            f"pid={lock.get('pid')} command={lock.get('command')} "
            f"current_action={lock.get('current_action')} pid_alive={lock.get('pid_alive')}"
        )
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


@app.command("fallback-requeue")
@app.command("scheduler-requeue-fallback")
def fallback_requeue_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    execute: bool = typer.Option(False, "--execute", help="Actually cancel and resubmit eligible jobs."),
    allow_outside_policy: bool = typer.Option(False, "--allow-outside-policy", help="Allow outside-wait-policy fallback requeues."),
    allow_carried_forward: bool = typer.Option(False, "--allow-carried-forward", help="Allow requeue from carried-forward wait evidence."),
    to_preferred: bool = typer.Option(False, "--to-preferred", help="Requeue a pending fallback job back to its configured preferred partition."),
    run_id: list[str] = typer.Option([], "--run-id", help="Run id to execute. May be supplied more than once."),
    all_runs: bool = typer.Option(False, "--all", help="Execute all eligible fallback requeues."),
) -> None:
    """List or explicitly execute scheduler fallback requeue recommendations."""

    if execute and not run_id and not all_runs:
        console.print("[red]--execute requires --run-id <run> or --all[/red]")
        raise typer.Exit(2)
    result = operator_fallback_requeue(
        paths(target),
        execute=execute,
        allow_outside_policy=allow_outside_policy,
        allow_carried_forward=allow_carried_forward,
        to_preferred=to_preferred,
        run_ids=run_id,
        all_runs=all_runs,
    )
    console.print_json(data=result)


@app.command("auto-next")
@app.command("compute-next")
def auto_next_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    offline: bool = typer.Option(False, "--offline"),
    dry_submit: bool = typer.Option(False, "--dry-submit", help="Record backend submissions without launching jobs."),
    real_submit: bool = typer.Option(False, "--real-submit", help="Explicitly allow real backend submission."),
    force_lock: bool = typer.Option(False, "--force-lock", help="Override a stale advancing lock after validation."),
) -> None:
    """Execute one safe next step from the local state machine."""

    console.print(run_auto_next(paths(target), offline=offline, dry_submit=effective_dry_submit(dry_submit, real_submit), force_lock=force_lock))


@app.command("auto-cycle")
def auto_cycle_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    offline: bool = typer.Option(False, "--offline"),
    dry_submit: bool = typer.Option(False, "--dry-submit", help="Record backend submissions without launching jobs."),
    real_submit: bool = typer.Option(False, "--real-submit", help="Explicitly allow real backend submission."),
    max_steps: int = typer.Option(30, "--max-steps"),
    force_lock: bool = typer.Option(False, "--force-lock", help="Override a stale advancing lock after validation."),
) -> None:
    """Advance one portfolio cycle until submit/manual/block."""

    for line in run_auto_cycle(paths(target), offline=offline, dry_submit=effective_dry_submit(dry_submit, real_submit), max_steps=max_steps, force_lock=force_lock):
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


@app.command("lit-refresh-idea")
def lit_refresh_idea_cmd(
    idea_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    offline: bool = typer.Option(False, "--offline"),
    source: str = typer.Option("openalex", "--source"),
    limit: int = typer.Option(5, "--limit"),
) -> None:
    """Run a bounded literature refresh for an idea-pool entry and mark it actionable."""

    console.print_json(data=literature_refresh_idea(paths(target), idea_id, offline=offline, source=source, limit=limit))


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


@app.command("auto-method-search")
def auto_method_search_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    offline: bool = typer.Option(False, "--offline"),
    force: bool = typer.Option(False, "--force"),
) -> None:
    """Run the bounded project-aware online method search used by auto-cycle."""

    console.print_json(data=auto_method_search(paths(target), offline=offline, force=force))


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
    mode: str = typer.Option("auto-cycle", "--mode", help="Daemon loop mode: auto-cycle or monitor."),
    offline: bool = typer.Option(False, "--offline/--online", help="Disable or allow external search calls inside auto-cycle."),
    dry_submit: bool = typer.Option(False, "--dry-submit", help="Record submissions without launching backend jobs."),
    real_submit: bool = typer.Option(False, "--real-submit", help="Explicitly allow real backend submission."),
    max_steps: int = typer.Option(30, "--max-steps", help="Maximum auto-next steps per auto-cycle iteration."),
) -> None:
    """Start a tmux supervisor running an autonomous or monitor-only loop."""

    try:
        console.print(daemon_start(paths(target), interval=interval, auto_next=auto_next, mode=mode, offline=offline, dry_submit=effective_dry_submit(dry_submit, real_submit), max_steps=max_steps))
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc


@daemon_app.command("stop")
def daemon_stop_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Stop the tmux supervisor."""

    console.print(daemon_stop(paths(target)))


@daemon_app.command("status")
def daemon_status_cmd(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Show tmux supervisor status."""

    console.print(daemon_status(paths(target)))


@daemon_app.command("audit-autonomy")
def daemon_audit_autonomy_cmd(
    target: Path = typer.Option(Path("."), "--target", "-t"),
    expect_autonomous: bool = typer.Option(True, "--expect-autonomous/--no-expect-autonomous"),
    expect_real_submit: bool = typer.Option(False, "--expect-real-submit"),
) -> None:
    """Fail if daemon mode cannot advance an actionable autonomous next step."""

    result = daemon_autonomy_audit(paths(target), expect_autonomous=expect_autonomous, expect_real_submit=expect_real_submit)
    console.print_json(data=result)
    if not result.get("ok"):
        raise typer.Exit(1)


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
