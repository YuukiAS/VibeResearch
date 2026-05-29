"""Command line interface for VibeResearch."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .dashboard import render_leaderboard, render_status, sync_dashboard
from .git_ops import abandon_run, create_branch, merge_run
from .io import read_json
from .paths import VibePaths
from .project import add_directive, add_idea, create_cycle, generate_runs, init_project
from .research import deep_request, ingest_deep_research, literature_refresh, reflect, reflect_cycle, revise_cycle, revise_plan
from .scheduler import collect as collect_run
from .scheduler import monitor as monitor_jobs
from .scheduler import queue_run, review_cycle, review_run, run_dryrun, submit_queue
from .timeline import render_timeline_markdown, sync_timeline_files

app = typer.Typer(help="Repo-specific sustained Vibe Research orchestration.")
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
    state = read_json(p.state / "state.json", {})
    action = state.get("next_action", "vibe status")
    blocked = state.get("blocked_reason", "")
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
) -> None:
    """Create a portfolio plan for the next cycle."""

    cycle_id = create_cycle(paths(target), mode=mode)
    console.print(f"Created cycle {cycle_id}")


@app.command("review-cycle")
def review_cycle_cmd(cycle_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Approve or guard a cycle-level portfolio scaffold."""

    review_cycle(paths(target), cycle_id)
    console.print(f"Reviewed {cycle_id}")


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
def review(run_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Write a guarded run review scaffold."""

    review_run(paths(target), run_id)
    console.print(f"Reviewed {run_id}")


@app.command()
def branch(run_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Create or record the per-run branch."""

    name = create_branch(paths(target), run_id)
    console.print(f"Branch ready: {name}")


@app.command()
def patch(run_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Record current diff placeholder for a run.

    This command is intentionally conservative. Codex should generate patches,
    while runner records and validates them before execution.
    """

    p = paths(target)
    p.require_initialized()
    patch_path = p.runs / run_id / "patch.diff"
    if not patch_path.exists():
        raise typer.BadParameter(f"Unknown run: {run_id}")
    console.print(f"Patch artifact: {patch_path}")


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
) -> None:
    """Submit queued runs within scheduler budget."""

    submitted = submit_queue(paths(target), dry=dry)
    console.print(f"Submitted: {', '.join(submitted) if submitted else 'none'}")


@app.command()
def monitor(target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Poll active jobs without LLM calls."""

    monitor_jobs(paths(target))
    console.print("Monitor pass complete")


@app.command()
def collect(
    run_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    metric: Optional[float] = typer.Option(None, "--metric"),
    trusted: bool = typer.Option(False, "--trusted"),
) -> None:
    """Collect metrics and update leaderboard history."""

    collect_run(paths(target), run_id, metric=metric, trusted=trusted)
    console.print(f"Collected {run_id}")


def reflect_cmd(run_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Generate run-level reflection."""

    reflect(paths(target), run_id)
    console.print(f"Reflected {run_id}")


app.command("reflect")(reflect_cmd)


@app.command("revise-plan")
def revise_plan_cmd(
    run_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    decision: str = typer.Option("collect_more_metrics", "--decision"),
) -> None:
    """Generate mandatory run-level revised plan."""

    revise_plan(paths(target), run_id, decision=decision)
    console.print(f"Revised plan for {run_id}")


@app.command("reflect-cycle")
def reflect_cycle_cmd(cycle_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Generate cycle-level reflection."""

    reflect_cycle(paths(target), cycle_id)
    console.print(f"Reflected cycle {cycle_id}")


@app.command("revise-cycle")
def revise_cycle_cmd(
    cycle_id: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    mode: Optional[str] = typer.Option(None, "--mode"),
) -> None:
    """Generate mandatory cycle-level revised plan."""

    revise_cycle(paths(target), cycle_id, mode=mode)
    console.print(f"Revised cycle {cycle_id}")


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
) -> None:
    """Generate a standard deep research request."""

    request_id = deep_request(paths(target), request_for=run_id, topic=topic, blocking=blocking)
    console.print(f"Created {request_id}")


@app.command("deep-request-cycle")
def deep_request_cycle_cmd(
    cycle_id: str,
    topic: str,
    target: Path = typer.Option(Path("."), "--target", "-t"),
    blocking: bool = typer.Option(False, "--blocking"),
) -> None:
    """Generate a cycle-level deep research request."""

    request_id = deep_request(paths(target), request_for=cycle_id, topic=topic, blocking=blocking)
    console.print(f"Created {request_id}")


@app.command("ingest-deep-research")
def ingest_deep_research_cmd(request_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Ingest a returned deep research report from raw/deep_reports."""

    ingest_deep_research(paths(target), request_id)
    console.print(f"Ingested {request_id}")


@app.command("wiki-ingest")
def wiki_ingest(paper_id: str, target: Path = typer.Option(Path("."), "--target", "-t")) -> None:
    """Placeholder for paper-to-wiki ingest."""

    p = paths(target)
    p.require_initialized()
    note = p.research / "wiki" / "papers" / f"{paper_id}.md"
    note.write_text(f"# Paper {paper_id}\n\nStatus: pending ingest.\n")
    sync_dashboard(p)
    console.print(f"Created {note}")


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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
