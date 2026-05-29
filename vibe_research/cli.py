"""Command line interface for VibeResearch."""

from __future__ import annotations

from pathlib import Path
import time
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .artifacts import validate_artifact, validate_hard_rules
from .automation import auto_cycle as run_auto_cycle
from .automation import auto_next as run_auto_next
from .automation import scheduler_explain as render_scheduler_explain
from .codex_adapter import artifact_path, prompt_packet, run_codex
from .config import migrate_project
from .daemon import daemon_start, daemon_status, daemon_stop
from .dashboard import render_leaderboard, render_status, sync_dashboard
from .directions import set_direction_status
from .git_ops import abandon_run, create_branch, git_available, git_current_branch, git_diff_text, merge_review, merge_run, protected_diff_paths
from .io import read_json
from .manifest import validate_manifest
from .next_action import compute_next_action
from .papers import add_paper, download_paper, list_papers, paper_search, pdf_to_markdown, wiki_ingest_paper
from .paths import VibePaths
from .project import add_directive, add_idea, create_cycle, generate_runs, init_project, sync_resource_plan_from_portfolio
from .research import deep_request, ingest_deep_research, literature_refresh, reflect, reflect_cycle, revise_cycle, revise_plan
from .scheduler import collect as collect_run
from .scheduler import cancel_run, monitor as monitor_jobs
from .scheduler import queue_run, review_cycle, review_run, run_dryrun, submit_queue
from .timeline import render_timeline_markdown, sync_timeline_files

app = typer.Typer(help="Repo-specific sustained Vibe Research orchestration.")
daemon_app = typer.Typer(help="Manage tmux-backed VibeResearch daemon.")
app.add_typer(daemon_app, name="daemon")
console = Console()


def paths(target: Path) -> VibePaths:
    return VibePaths(target)


@app.command()
def init(
    target: Path = typer.Option(Path("."), "--target", "-t", help="Target repository to initialize."),
    project_name: Optional[str] = typer.Option(None, "--project-name"),
    force: bool = typer.Option(False, "--force", help="Rewrite generated Vibe files."),
) -> None:
    """Initialize `.vibe/` and root progress files in a target repo."""

    p = init_project(target, project_name=project_name, force=force)
    console.print(f"Initialized VibeResearch at [bold]{p.root}[/bold]")


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
    cycle_id = create_cycle(p, mode=mode)
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

    run_ids = generate_runs(paths(target), cycle_id=cycle_id, count=count)
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

    queue_run(paths(target), run_id)
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
    revise_plan(p, run_id, decision=decision, keep_existing=True)
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
    revise_cycle(p, cycle_id, mode=mode, keep_existing=True)
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


@app.command("ingest-deep-research")
def ingest_deep_research_cmd(request_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Ingest a returned deep research report from raw/deep_reports."""

    ingest_deep_research(paths(target), request_id)
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
