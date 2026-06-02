"""Literature and deep research local interfaces."""

from __future__ import annotations

from .dashboard import sync_dashboard
import re

from .decisions import BLOCK_DECISIONS, ensure_decision_after_revise
from .ideas import create_idea as create_pool_idea
from .ideas import get_idea, update_idea
from .ideas import sync_plan_idea_updates
from .human_guidance import sync_guidance_after_reflect
from .io import append_jsonl, ensure_dir, read_json, read_jsonl, utc_now, write_json, write_text
from .loop_guard import apply_loop_guard
from .papers import add_paper, paper_search
from .paths import VibePaths
from .promotion import compile_decision as compile_cycle_decision
from .scheduler import promote_trusted_candidate
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
    sync_guidance_after_reflect(paths, run_id, text + "\n" + str(metrics))
    sync_dashboard(paths)


def revise_plan(paths: VibePaths, run_id: str, decision: str = "collect_more_metrics", *, keep_existing: bool = False, offline: bool = False) -> None:
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
    structured = ensure_decision_after_revise(paths, run_id, revised_path.read_text(), offline=offline)
    loop_block = apply_loop_guard(paths, run_id)
    state = read_json(paths.state / "state.json", {})
    run = state.get("runs", {}).get(run_id, run)
    blocked = bool(loop_block) or structured.decision_type in BLOCK_DECISIONS
    if not blocked:
        promote_trusted_candidate(paths, run_id)
        state = read_json(paths.state / "state.json", {})
        run = state.get("runs", {}).get(run_id, run)
    run["status"] = "blocked" if blocked else "revised"
    state["runs"][run_id] = run
    if blocked:
        state["next_action"] = f"vibe decision show {run_id}"
    else:
        state["blocked_reason"] = ""
        state["next_action"] = f"vibe reflect-cycle {run.get('cycle_id', '')}"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    status = "blocked" if blocked else "revised"
    record_event(paths, "run_revised_plan_written", f"Decision={structured.decision_type}", cycle_id=run.get("cycle_id", ""), run_id=run_id, status=status)
    sync_dashboard(paths)


def reflect_cycle(paths: VibePaths, cycle_id: str, *, keep_existing: bool = False) -> None:
    state = read_json(paths.state / "state.json", {})
    runs = [run_id for run_id, run in state.get("runs", {}).items() if run.get("cycle_id") == cycle_id]
    body = "\n".join(f"- {run_id}: {state['runs'][run_id].get('status')}" for run_id in runs) or "- none"
    classification = render_cycle_route_classification(paths, state, runs)
    external = render_recent_external_evidence(paths)
    reflect_path = paths.cycles / cycle_id / "cycle_reflect.md"
    existing_text = reflect_path.read_text() if reflect_path.exists() else ""
    if not keep_existing or not reflect_path.exists() or not existing_text.strip():
        write_text(
            reflect_path,
            f"# Cycle Reflect for {cycle_id}\n\n"
            f"## Run comparison\n{body}\n\n"
            f"## Route classification\n{classification}\n\n"
            f"## External evidence consulted\n{external}\n\n"
            f"## Next-round requirements\n"
            f"- Compare at least two distinct routes before repeating a mechanism.\n"
            f"- Use trusted metric/schema evidence where available; mark missing evidence explicitly.\n",
        )
    else:
        additions = []
        if "## Route classification" not in existing_text:
            additions.append(f"## Route classification\n{classification}\n")
        if "## External evidence consulted" not in existing_text:
            additions.append(f"## External evidence consulted\n{external}\n")
        if "## Next-round requirements" not in existing_text:
            additions.append(
                "## Next-round requirements\n"
                "- Compare at least two distinct routes before repeating a mechanism.\n"
                "- Use trusted metric/schema evidence where available; mark missing evidence explicitly.\n"
            )
        if additions:
            write_text(reflect_path, existing_text.rstrip() + "\n\n" + "\n\n".join(additions))
    state.setdefault("cycles", {}).setdefault(cycle_id, {})["status"] = "reflected"
    state["next_action"] = f"vibe revise-cycle {cycle_id}"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "cycle_reflect_written", f"Reflected {len(runs)} runs", cycle_id=cycle_id, status="reflected")
    sync_dashboard(paths)


def revise_cycle(paths: VibePaths, cycle_id: str, mode: str | None = None, *, keep_existing: bool = False, offline: bool = False) -> None:
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

## Next-cycle diversity requirement
Plan a bounded multi-route portfolio unless the evidence justifies narrowing.

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
    existing_revised = revised_path.read_text() if revised_path.exists() else ""
    if not keep_existing or not revised_path.exists() or not existing_revised.strip():
        write_text(revised_path, text)
    elif "## Next-cycle diversity requirement" not in existing_revised:
        write_text(
            revised_path,
            existing_revised.rstrip()
            + "\n\n## Next-cycle diversity requirement\nPlan a bounded multi-route portfolio unless the evidence justifies narrowing.\n",
        )
    ensure_idea_update_section(revised_path)
    sync_plan_idea_updates(paths, revised_path.read_text())
    structured = ensure_decision_after_revise(paths, cycle_id, revised_path.read_text(), offline=offline)
    loop_block = apply_loop_guard(paths, cycle_id)
    compiled_ok = False
    if structured.decision_type not in BLOCK_DECISIONS and not loop_block:
        compiled_ok, _ = compile_cycle_decision(paths, cycle_id)
    state = read_json(paths.state / "state.json", {})
    blocked = bool(loop_block) or structured.decision_type in BLOCK_DECISIONS or not compiled_ok
    state.setdefault("cycles", {}).setdefault(cycle_id, {})["status"] = "blocked" if blocked else "revised"
    state["portfolio_mode"] = next_mode
    if blocked:
        state["next_action"] = f"vibe decision show {cycle_id}"
    else:
        state["blocked_reason"] = ""
        state["next_action"] = "vibe plan-cycle"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    record_event(paths, "cycle_revised_plan_written", f"Decision={structured.decision_type}; next mode={next_mode}", cycle_id=cycle_id, status="blocked" if blocked else "revised")
    sync_dashboard(paths)


def render_cycle_route_classification(paths: VibePaths, state: dict, run_ids: list[str]) -> str:
    lines = []
    for run_id in run_ids:
        run = state.get("runs", {}).get(run_id, {})
        metrics = read_json(paths.runs / run_id / "metrics.json", {})
        trusted = bool(metrics.get("trusted") or metrics.get("provenance"))
        classification = "trusted_metric" if trusted else "needs_trust_evidence"
        primary = metrics.get("primary_metric", metrics.get("primary", ""))
        metadata = run.get("adapter_metadata", {}) if isinstance(run.get("adapter_metadata"), dict) else {}
        lines.append(
            f"- `{run_id}` route={run.get('direction_id', '') or metadata.get('capability_id', '')} "
            f"status={run.get('status', '')} classification={classification} primary={primary}"
        )
    return "\n".join(lines) if lines else "- none"


def render_recent_external_evidence(paths: VibePaths) -> str:
    rows = read_jsonl(paths.research / "sources.jsonl")[-5:]
    repos = read_jsonl(paths.research / "external_repos.jsonl")[-5:]
    lines = []
    for row in rows:
        lines.append(f"- source={row.get('source', '')} context={row.get('context_id', '')} query={row.get('query', '')} results={len(row.get('results', []))}")
    for row in repos:
        lines.append(f"- external_repo={row.get('name', '')} url={row.get('url', '')} status={row.get('status', '')}")
    return "\n".join(lines) if lines else "- none"


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


def literature_refresh_idea(paths: VibePaths, idea_id: str, *, offline: bool = False, source: str = "openalex", limit: int = 5) -> dict[str, object]:
    idea = get_idea(paths, idea_id)
    query = idea.get("raw_text", "")[:500]
    results = paper_search(paths, query, source=source, limit=limit, offline=offline, add_candidates=not offline)
    non_error = [row for row in results if not row.get("error")]
    source_evidence = [
        " | ".join(str(part) for part in [row.get("title", ""), row.get("source_url", "") or row.get("pdf_url", "")] if part)
        for row in non_error
        if row.get("title") or row.get("source_url") or row.get("pdf_url")
    ]
    ensure_dir(paths.research / "idea_literature_refresh")
    artifact = paths.research / "idea_literature_refresh" / f"{idea_id}.json"
    payload: dict[str, object] = {
        "idea_id": idea_id,
        "created_at": utc_now(),
        "query": query,
        "source": source,
        "offline": offline,
        "results": results,
        "non_error_count": len(non_error),
        "source_evidence": source_evidence,
    }
    write_json(artifact, payload)
    linked = list(idea.get("linked_evidence", []) or [])
    linked.extend([str(artifact), ".vibe/research/sources.jsonl", *source_evidence])
    status = "actionable_next_run" if non_error or "http" in query.lower() else "needs_deep_research"
    next_action = "include in next portfolio plan" if status == "actionable_next_run" else f"vibe deep-request-from-idea {idea_id}"
    updated = update_idea(
        paths,
        idea_id,
        status=status,
        linked_evidence=sorted(set(linked)),
        current_evidence=f"literature refresh via {source}: {len(non_error)} usable results",
        next_action=next_action,
    )
    payload["updated_status"] = updated.get("status", "")
    write_json(artifact, payload)
    record_event(paths, "idea_literature_refreshed", idea_id, status=status, payload=payload)
    sync_dashboard(paths)
    return payload


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
    linked_idea_ids = []
    for row in read_jsonl(paths.research / "deep_requests" / "registry.jsonl"):
        if row.get("request_id") == request_id:
            linked_idea_ids = row.get("linked_idea_ids", [])
    for url in sorted(set(re.findall(r"https?://(?:arxiv\.org/abs|doi\.org|www\.semanticscholar\.org)[^\s)\]]+", report))):
        paper_id = add_paper(paths, {"title": url.rsplit("/", 1)[-1], "source_url": url, "status": "from_deep_research", "related_deep_request_ids": [request_id], "related_idea_ids": linked_idea_ids})
        paper_ids.append(paper_id)
    repo_urls = sorted(set(re.findall(r"https?://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", report)))
    dataset_mentions = extract_tagged_lines(report, ["dataset", "benchmark", "cohort", "数据集", "基准"])
    method_mentions = extract_tagged_lines(report, ["method", "model", "architecture", "approach", "方法", "模型"])
    risk_mentions = extract_tagged_lines(report, ["risk", "failure", "limitation", "guardrail", "风险", "失败"])
    write_text(comparison, "# Method Comparison Extract\n\n" + "\n".join(f"- {line}" for line in method_mentions[:80]) + "\n")
    write_text(gaps, "# Risks and Gaps Extract\n\n" + "\n".join(f"- {line}" for line in risk_mentions[:80]) + "\n")
    write_json(repos_path, {"request_id": request_id, "repo_urls": repo_urls})
    write_text(datasets_path, "# Dataset and Benchmark Mentions\n\n" + "\n".join(f"- {line}" for line in dataset_mentions[:80]) + "\n")
    concepts_path = paths.research / "wiki" / "concepts" / f"{request_id}_concepts.md"
    write_text(concepts_path, "# Concept Extract\n\n" + "\n".join(f"- {line}" for line in (method_mentions + dataset_mentions)[:80]) + "\n")
    for paper_id in paper_ids:
        write_text(paths.research / "wiki" / "papers" / f"{paper_id}.md", f"# Paper: {paper_id}\n\nLinked deep research request: `{request_id}`\n")
    append_repo_queue(paths, request_id, repo_urls)
    update_wiki_index(paths, request_id, [synthesis, comparison, gaps, datasets_path, concepts_path])
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
            row["wiki_updates"] = [str(synthesis), str(comparison), str(gaps), str(datasets_path), str(concepts_path)]
            row["decision_impact"] = f"updated_{kind}_wiki_papers_repos_datasets_inbox"
            row["kind"] = kind
        updated.append(row)
    write_text(registry_path, "".join(__import__("json").dumps(row, sort_keys=True) + "\n" for row in updated))
    record_event(paths, "deep_research_ingested", f"Ingested {request_id}", status="ingested", payload={"synthesis": str(synthesis), "papers": paper_ids, "repos": repo_urls, "ideas": ideas})
    sync_dashboard(paths)


def append_repo_queue(paths: VibePaths, request_id: str, repo_urls: list[str]) -> None:
    if not repo_urls:
        return
    queue_path = paths.research / "raw" / "repos" / "queue.jsonl"
    for url in repo_urls:
        append_jsonl(queue_path, {"created_at": utc_now(), "request_id": request_id, "repo_url": url, "status": "candidate"})


def update_wiki_index(paths: VibePaths, request_id: str, updates: list[object]) -> None:
    index = paths.research / "wiki" / "index.md"
    current = index.read_text() if index.exists() else "# Research Wiki\n\n"
    lines = [current.rstrip(), "", f"## Deep Research {request_id}", ""]
    for path in updates:
        lines.append(f"- {path}")
    write_text(index, "\n".join(lines) + "\n")
    overview = paths.research / "wiki" / "overview.md"
    prior = overview.read_text() if overview.exists() else "# Research Overview\n\n"
    write_text(overview, prior.rstrip() + f"\n\n- {utc_now()} updated from `{request_id}`.\n")


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
