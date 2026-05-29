"""Literature and deep research local interfaces."""

from __future__ import annotations

from .dashboard import sync_dashboard
from .io import append_jsonl, read_json, read_jsonl, utc_now, write_json, write_text
from .paths import VibePaths
from .timeline import record_event


def reflect(paths: VibePaths, run_id: str) -> None:
    state = read_json(paths.state / "state.json", {})
    run = state.get("runs", {}).get(run_id)
    if not run:
        raise ValueError(f"Unknown run: {run_id}")
    metrics = read_json(paths.runs / run_id / "metrics.json", {})
    text = f"""# Reflect for {run_id}

## Result interpretation
Primary metric: {metrics.get('primary_metric', 'unknown')}. Provenance present: {bool(metrics.get('provenance'))}.

## Hypothesis status
Needs reviewer interpretation.

## Failure or success analysis
This scaffold records the result and requires a revised plan before NEXT.
"""
    write_text(paths.runs / run_id / "reflect.md", text)
    run["status"] = "reflected"
    state["runs"][run_id] = run
    state["next_action"] = f"vibe revise-plan {run_id}"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "run_reflect_written", f"Wrote reflect.md for {run_id}", cycle_id=run.get("cycle_id", ""), run_id=run_id, status="reflected")
    sync_dashboard(paths)


def revise_plan(paths: VibePaths, run_id: str, decision: str = "collect_more_metrics") -> None:
    state = read_json(paths.state / "state.json", {})
    run = state.get("runs", {}).get(run_id)
    if not run:
        raise ValueError(f"Unknown run: {run_id}")
    text = f"""# Revised Plan for {run_id}

## Result interpretation
See `reflect.md`.

## Decision
{decision}

## Plan update
Continue only after this decision is reviewed against cycle-level priorities.

## Required changes
none

## Evidence needed
none

## Literature refresh decision
no

## Deep research decision
no

## Portfolio implication
Keep direction status unchanged until cycle reflection.

## Next experiment proposal
To be decided by `vibe revise-cycle {run.get('cycle_id', '')}`.

## Stop condition
Stop if repeated runs fail guardrails or provenance.
"""
    write_text(paths.runs / run_id / "revised_plan.md", text)
    run["status"] = "revised"
    state["runs"][run_id] = run
    state["next_action"] = f"vibe reflect-cycle {run.get('cycle_id', '')}"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "run_revised_plan_written", f"Decision={decision}", cycle_id=run.get("cycle_id", ""), run_id=run_id, status="revised")
    sync_dashboard(paths)


def reflect_cycle(paths: VibePaths, cycle_id: str) -> None:
    state = read_json(paths.state / "state.json", {})
    runs = [run_id for run_id, run in state.get("runs", {}).items() if run.get("cycle_id") == cycle_id]
    body = "\n".join(f"- {run_id}: {state['runs'][run_id].get('status')}" for run_id in runs) or "- none"
    write_text(paths.cycles / cycle_id / "cycle_reflect.md", f"# Cycle Reflect for {cycle_id}\n\n## Run comparison\n{body}\n")
    state.setdefault("cycles", {}).setdefault(cycle_id, {})["status"] = "reflected"
    state["next_action"] = f"vibe revise-cycle {cycle_id}"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "cycle_reflect_written", f"Reflected {len(runs)} runs", cycle_id=cycle_id, status="reflected")
    sync_dashboard(paths)


def revise_cycle(paths: VibePaths, cycle_id: str, mode: str | None = None) -> None:
    state = read_json(paths.state / "state.json", {})
    next_mode = mode or state.get("portfolio_mode", "exploration")
    text = f"""# Cycle Revised Plan for {cycle_id}

## Cycle-level interpretation
Use the run-level revised plans and leaderboard before selecting the next portfolio.

## Direction decisions
No direction is promoted or stopped by default in the scaffold.

## Portfolio mode update
{next_mode}

## Next portfolio sketch
Generate the next portfolio with `vibe plan-cycle`.

## Resource update
Use current scheduler budget.

## Literature and deep research decision
Literature refresh: no. Deep research: no.

## User decision needed
none

## Stop condition
Stop or shrink directions after repeated provenance or guardrail failures.
"""
    write_text(paths.cycles / cycle_id / "cycle_revised_plan.md", text)
    state.setdefault("cycles", {}).setdefault(cycle_id, {})["status"] = "revised"
    state["portfolio_mode"] = next_mode
    state["next_action"] = "vibe plan-cycle"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "cycle_revised_plan_written", f"Next mode={next_mode}", cycle_id=cycle_id, status="revised")
    sync_dashboard(paths)


def literature_refresh(paths: VibePaths, run_id: str | None = None, cycle_id: str | None = None, query: str = "") -> None:
    payload = {
        "created_at": utc_now(),
        "query": query,
        "sources": [],
        "results": [],
        "selected_papers": [],
        "rejected_papers": [],
        "downloaded_files": [],
        "wiki_updates": [],
        "changed_plan": False,
    }
    if run_id:
        write_json(paths.runs / run_id / "literature_refresh.json", payload)
    else:
        write_json(paths.cycles / (cycle_id or "cycle") / "literature_refresh.json", payload)
    record_event(paths, "literature_refreshed", query or "Recorded empty literature refresh", cycle_id=cycle_id or "", run_id=run_id or "", status="recorded", payload=payload)
    sync_dashboard(paths)


def deep_request(paths: VibePaths, *, request_for: str, topic: str, blocking: bool = False) -> str:
    existing = [row["request_id"] for row in read_jsonl(paths.research / "deep_requests" / "registry.jsonl")]
    number = len(existing) + 1
    request_id = f"dr{number:03d}_{topic.lower().replace(' ', '_')[:32]}"
    request_path = paths.research / "deep_requests" / f"{request_id}.md"
    text = f"""# Deep Research Request: {request_id}

## Project context
Target repo: `{paths.root}`.

## Current experimental evidence
See VIBE_LEADERBOARD.md and recent cycle/run reflections.

## Existing local knowledge
See `.vibe/research/wiki/index.md`.

## Core research question
{topic}

## Required comparisons
Compare method families, repos, weights, benchmarks, and risks relevant to this route.

## What counts as useful output
Actionable next experiments, stop/continue recommendation, evidence table, repo/weight list, and citations.

## What to avoid
Avoid generic surveys, unsourced claims, and suggestions that ignore local constraints.

## Expected deliverable
Evidence table, method map, repo/weight list, risk assessment, recommended next experiments, citations.
"""
    write_text(request_path, text)
    record = {
        "request_id": request_id,
        "created_at": utc_now(),
        "reason": topic,
        "blocking": blocking,
        "status": "created",
        "request_path": str(request_path),
        "result_path": "",
        "linked": request_for,
        "ingested_at": "",
        "wiki_updates": [],
        "decision_impact": "",
    }
    append_jsonl(paths.research / "deep_requests" / "registry.jsonl", record)
    record_event(paths, "deep_research_request_created", topic, status="blocking" if blocking else "nonblocking", payload=record)
    sync_dashboard(paths)
    return request_id


def ingest_deep_research(paths: VibePaths, request_id: str) -> None:
    result_path = paths.research / "raw" / "deep_reports" / f"{request_id}_result.md"
    if not result_path.exists():
        raise FileNotFoundError(f"Expected report at {result_path}")
    report = result_path.read_text()
    synthesis = paths.research / "wiki" / "synthesis" / f"{request_id}.md"
    write_text(synthesis, f"# Deep Research Synthesis: {request_id}\n\n{report[:12000]}\n")
    with (paths.research / "wiki" / "log.md").open("a") as handle:
        handle.write(f"- {utc_now()} ingested {request_id} into {synthesis}\n")
    record_event(paths, "deep_research_ingested", f"Ingested {request_id}", status="ingested", payload={"synthesis": str(synthesis)})
    sync_dashboard(paths)

