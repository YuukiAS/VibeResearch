"""Literature and deep research local interfaces."""

from __future__ import annotations

from .dashboard import sync_dashboard
import re

from .ideas import create_idea as create_pool_idea
from .ideas import sync_plan_idea_updates
from .io import append_jsonl, ensure_dir, read_json, read_jsonl, utc_now, write_json, write_text
from .papers import add_paper
from .paths import VibePaths
from .timeline import record_event


def reflect(paths: VibePaths, run_id: str, *, keep_existing: bool = False) -> None:
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
    reflect_path = paths.runs / run_id / "reflect.md"
    if not keep_existing or not reflect_path.exists() or not reflect_path.read_text().strip():
        write_text(reflect_path, text)
    run["status"] = "reflected"
    state["runs"][run_id] = run
    state["next_action"] = f"vibe revise-plan {run_id}"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "run_reflect_written", f"Wrote reflect.md for {run_id}", cycle_id=run.get("cycle_id", ""), run_id=run_id, status="reflected")
    sync_dashboard(paths)


def revise_plan(paths: VibePaths, run_id: str, decision: str = "collect_more_metrics", *, keep_existing: bool = False) -> None:
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

## Idea pool update
- no changes

## Portfolio implication
Keep direction status unchanged until cycle reflection.

## Next experiment proposal
To be decided by `vibe revise-cycle {run.get('cycle_id', '')}`.

## Stop condition
Stop if repeated runs fail guardrails or provenance.
"""
    revised_path = paths.runs / run_id / "revised_plan.md"
    if not keep_existing or not revised_path.exists() or not revised_path.read_text().strip():
        write_text(revised_path, text)
    ensure_idea_update_section(revised_path)
    sync_plan_idea_updates(paths, revised_path.read_text())
    run["status"] = "revised"
    state["runs"][run_id] = run
    state["next_action"] = f"vibe reflect-cycle {run.get('cycle_id', '')}"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "run_revised_plan_written", f"Decision={decision}", cycle_id=run.get("cycle_id", ""), run_id=run_id, status="revised")
    sync_dashboard(paths)


def reflect_cycle(paths: VibePaths, cycle_id: str, *, keep_existing: bool = False) -> None:
    state = read_json(paths.state / "state.json", {})
    runs = [run_id for run_id, run in state.get("runs", {}).items() if run.get("cycle_id") == cycle_id]
    body = "\n".join(f"- {run_id}: {state['runs'][run_id].get('status')}" for run_id in runs) or "- none"
    reflect_path = paths.cycles / cycle_id / "cycle_reflect.md"
    if not keep_existing or not reflect_path.exists() or not reflect_path.read_text().strip():
        write_text(reflect_path, f"# Cycle Reflect for {cycle_id}\n\n## Run comparison\n{body}\n")
    state.setdefault("cycles", {}).setdefault(cycle_id, {})["status"] = "reflected"
    state["next_action"] = f"vibe revise-cycle {cycle_id}"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "cycle_reflect_written", f"Reflected {len(runs)} runs", cycle_id=cycle_id, status="reflected")
    sync_dashboard(paths)


def revise_cycle(paths: VibePaths, cycle_id: str, mode: str | None = None, *, keep_existing: bool = False) -> None:
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

## Idea pool update
- no changes

## User decision needed
none

## Stop condition
Stop or shrink directions after repeated provenance or guardrail failures.
"""
    revised_path = paths.cycles / cycle_id / "cycle_revised_plan.md"
    if not keep_existing or not revised_path.exists() or not revised_path.read_text().strip():
        write_text(revised_path, text)
    ensure_idea_update_section(revised_path)
    sync_plan_idea_updates(paths, revised_path.read_text())
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
    linked_cycle_ids = [request_for] if request_for.startswith("c") else []
    linked_run_ids = [request_for] if request_for.startswith("r") else []
    record = {
        "request_id": request_id,
        "created_at": utc_now(),
        "reason": topic,
        "blocking": blocking,
        "status": "created",
        "request_path": str(request_path),
        "result_path": "",
        "linked_cycle_ids": linked_cycle_ids,
        "linked_run_ids": linked_run_ids,
        "linked_revised_plan": "",
        "ingested_at": "",
        "wiki_updates": [],
        "decision_impact": "",
    }
    append_jsonl(paths.research / "deep_requests" / "registry.jsonl", record)
    record_event(paths, "deep_research_request_created", topic, status="blocking" if blocking else "nonblocking", payload=record)
    sync_dashboard(paths)
    return request_id


def ingest_deep_research(paths: VibePaths, request_id: str, *, kind: str = "science") -> None:
    result_path = paths.research / "raw" / "deep_reports" / f"{request_id}_result.md"
    pdf_path = paths.research / "raw" / "deep_reports" / f"{request_id}_result.pdf"
    if not result_path.exists():
        if pdf_path.exists():
            result_path = extract_deep_report_pdf(paths, request_id, pdf_path)
        else:
            raise FileNotFoundError(f"Expected report at {result_path} or {pdf_path}")
    report = result_path.read_text()
    synthesis = paths.research / "wiki" / "synthesis" / f"{request_id}.md"
    write_text(synthesis, f"# Deep Research Synthesis: {request_id}\n\n{report[:12000]}\n")
    comparison = paths.research / "wiki" / "comparisons" / f"{request_id}_methods.md"
    gaps = paths.research / "wiki" / "gaps" / f"{request_id}_risks.md"
    repos_path = paths.research / "raw" / "repos" / f"{request_id}_repos.json"
    datasets_path = paths.research / "wiki" / "entities" / f"{request_id}_datasets.md"
    paper_ids = []
    for url in sorted(set(re.findall(r"https?://(?:arxiv\.org/abs|doi\.org|www\.semanticscholar\.org)[^\s)\]]+", report))):
        paper_id = add_paper(paths, {"title": url.rsplit("/", 1)[-1], "source_url": url, "status": "from_deep_research", "related_deep_request_ids": [request_id]})
        paper_ids.append(paper_id)
    repo_urls = sorted(set(re.findall(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", report)))
    dataset_mentions = extract_tagged_lines(report, ["dataset", "benchmark", "cohort", "数据集", "基准"])
    method_mentions = extract_tagged_lines(report, ["method", "model", "architecture", "approach", "方法", "模型"])
    risk_mentions = extract_tagged_lines(report, ["risk", "failure", "limitation", "guardrail", "风险", "失败"])
    write_text(comparison, "# Method Comparison Extract\n\n" + "\n".join(f"- {line}" for line in method_mentions[:80]) + "\n")
    write_text(gaps, "# Risks and Gaps Extract\n\n" + "\n".join(f"- {line}" for line in risk_mentions[:80]) + "\n")
    write_json(repos_path, {"request_id": request_id, "repo_urls": repo_urls})
    write_text(datasets_path, "# Dataset and Benchmark Mentions\n\n" + "\n".join(f"- {line}" for line in dataset_mentions[:80]) + "\n")
    ideas = []
    for line in report.splitlines():
        lowered = line.lower()
        if any(token in lowered for token in ["recommend", "next experiment", "try ", "建议", "下一步"]):
            text = line.strip("-* ")
            if text:
                ideas.append(text[:300])
                pool = create_pool_idea(paths, text[:300], source="deep_research", status="triaged")
                append_jsonl(
                    paths.inbox / "triage.jsonl",
                    {
                        "idea_id": pool["idea_id"],
                        "created_at": utc_now(),
                        "source": "deep_research",
                        "raw_text": text[:300],
                        "status": "new",
                        "linked_deep_request_id": request_id,
                        "linked_pool_idea_id": pool["idea_id"],
                        "triage_decision": "experiment_candidate",
                    },
                )
    with (paths.research / "wiki" / "log.md").open("a") as handle:
        handle.write(f"- {utc_now()} ingested {request_id} into {synthesis}\n")
    registry_path = paths.research / "deep_requests" / "registry.jsonl"
    updated = []
    for row in read_jsonl(registry_path):
        if row.get("request_id") == request_id:
            row["status"] = "ingested"
            row["result_path"] = str(result_path)
            row["ingested_at"] = utc_now()
            row["wiki_updates"] = [str(synthesis), str(comparison), str(gaps), str(datasets_path)]
            row["decision_impact"] = f"updated_{kind}_wiki_papers_repos_datasets_inbox"
            row["kind"] = kind
        updated.append(row)
    write_text(registry_path, "".join(__import__("json").dumps(row, sort_keys=True) + "\n" for row in updated))
    record_event(paths, "deep_research_ingested", f"Ingested {request_id}", status="ingested", payload={"synthesis": str(synthesis), "papers": paper_ids, "repos": repo_urls, "ideas": ideas})
    sync_dashboard(paths)


def extract_deep_report_pdf(paths: VibePaths, request_id: str, pdf_path) -> object:
    md = paths.research / "raw" / "deep_reports" / f"{request_id}_result.md"
    ensure_dir(md.parent)
    text = ""
    method = "unavailable"
    try:
        import fitz  # type: ignore

        doc = fitz.open(str(pdf_path))
        text = "\n".join(page.get_text() for page in doc)
        method = "pymupdf"
    except Exception as exc:
        text = f"PDF text extraction unavailable: {exc}"
    write_text(md, f"# Deep Research PDF Extract: {request_id}\n\nExtraction method: {method}\nSource PDF: {pdf_path}\n\n{text[:200000]}\n")
    return md


def extract_tagged_lines(text: str, tags: list[str]) -> list[str]:
    rows = []
    for line in text.splitlines():
        clean = line.strip("-*# \t")
        lowered = clean.lower()
        if clean and any(tag in lowered for tag in tags):
            rows.append(clean[:500])
    return rows


def ensure_idea_update_section(path) -> None:
    text = path.read_text() if path.exists() else ""
    if "## Idea pool update" not in text:
        path.write_text(text.rstrip() + "\n\n## Idea pool update\n- no changes\n")
