"""Evidence-grounded living research brief files."""

from __future__ import annotations

from typing import Any

from .config import load_config
from .human_guidance import active_human_guidance, ensure_human_guidance
from .io import read_json, read_jsonl, utc_now, write_json, write_text
from .knowledge_lifecycle import unconsumed_plan_candidate_cards
from .paths import VibePaths
from .real_experiments import summarize_real_experiment_progress


def update_living_research_brief(paths: VibePaths, *, language: str | None = None) -> dict[str, Any]:
    ensure_human_guidance(paths)
    config = load_config(paths)
    preferred = normalize_brief_language(language or config.get("research", {}).get("brief_language", "zh"))
    context = living_brief_context(paths)
    zh = render_living_brief(context, language="zh")
    en = render_living_brief(context, language="en")
    zh_path = paths.research / "CURRENT_RESEARCH_BRIEF.zh.md"
    en_path = paths.research / "CURRENT_RESEARCH_BRIEF.en.md"
    json_path = paths.research / "research_brief.json"
    write_text(zh_path, zh)
    write_text(en_path, en)
    payload = {
        "schema_version": 1,
        "created_at": utc_now(),
        "preferred_language": preferred,
        "brief_language": preferred,
        "files": {
            "zh": str(zh_path.relative_to(paths.root)),
            "en": str(en_path.relative_to(paths.root)),
        },
        "sections": context,
    }
    write_json(json_path, payload)
    return {"preferred_language": preferred, "path": str((zh_path if preferred == "zh" else en_path).relative_to(paths.root)), "json_path": str(json_path.relative_to(paths.root))}


def living_brief_context(paths: VibePaths) -> dict[str, Any]:
    state = read_json(paths.state / "state.json", {})
    project = read_json(paths.vibe / "config.json", {}).get("project", {})
    progress = summarize_real_experiment_progress(paths)
    active_guidance = active_human_guidance(paths)
    cards = unconsumed_plan_candidate_cards(paths)
    recent_decisions = read_jsonl(paths.state / "decisions.jsonl")[-5:]
    evidence_rows = read_jsonl(paths.kernel / "EVIDENCE_LEDGER.jsonl")
    negative_memory = read_text_tail(paths.kernel / "NEGATIVE_MEMORY.md")
    open_debts = read_text_tail(paths.kernel / "OPEN_DEBTS.md")
    failure_signatures = read_text_tail(paths.kernel / "FAILURE_SIGNATURES.md")
    runs = state.get("runs", {}) if isinstance(state.get("runs"), dict) else {}
    positive, negative = recent_run_signals(paths, runs)
    needs_user = [row for row in recent_decisions if str(row.get("decision_type", "")).startswith("blocked_") or row.get("decision_type") == "ask_user"]
    return {
        "project_goal": project.get("goal", "") or "MISSING",
        "current_cycle": state.get("current_cycle_id") or "none",
        "state_status": state.get("status", "unknown"),
        "next_action": state.get("next_action", "vibe next"),
        "blocked_reason": state.get("blocked_reason", ""),
        "failure_signatures": failure_signatures,
        "positive_signals": positive,
        "negative_evidence": negative,
        "open_debts": open_debts,
        "negative_memory": negative_memory,
        "evidence_count": len(evidence_rows),
        "real_experiment_progress": {
            "observed_count": progress.get("observed_count", 0),
            "target_count": progress.get("target_count", 3),
            "next_action": progress.get("next_action", ""),
        },
        "active_guidance": active_guidance[-5:],
        "unconsumed_mechanism_cards": cards[:5],
        "user_decision_needed": needs_user[-3:],
        "uncertainty": uncertainty_summary(open_debts, cards, progress),
        "created_at": utc_now(),
    }


def recent_run_signals(paths: VibePaths, runs: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    positive: list[dict[str, Any]] = []
    negative: list[dict[str, Any]] = []
    for run_id, run in sorted(runs.items())[-20:]:
        metrics = read_json(paths.runs / run_id / "metrics.json", {})
        row = {
            "run_id": run_id,
            "status": run.get("status", ""),
            "direction_id": run.get("direction_id", ""),
            "trust_status": metrics.get("trust_status", ""),
            "schema_status": metrics.get("schema_status", ""),
            "primary_metric": metrics.get("primary_metric", metrics.get("primary", "")),
        }
        if metrics.get("trusted") or metrics.get("schema_status") == "valid":
            positive.append(row)
        elif run.get("status") in {"failed", "timeout", "blocked", "dryrun_failed"}:
            negative.append(row)
    return positive[-5:], negative[-5:]


def render_living_brief(context: dict[str, Any], *, language: str) -> str:
    if language == "en":
        return render_en(context)
    return render_zh(context)


def render_zh(context: dict[str, Any]) -> str:
    guidance = guidance_sentence(context, zh=True)
    cards = card_sentence(context, zh=True)
    user = user_decision_sentence(context, zh=True)
    return (
        "# CURRENT_RESEARCH_BRIEF.zh\n\n"
        f"当前项目目标是：{context['project_goal']}。系统处在 `{context['state_status']}` 状态，"
        f"当前 cycle 是 `{context['current_cycle']}`，下一步建议是 `{context['next_action']}`。"
        f"{(' 当前阻塞原因为：' + context['blocked_reason'] + '。') if context.get('blocked_reason') else ''}\n\n"
        f"主要失败签名来自 `FAILURE_SIGNATURES.md`：{compact(context.get('failure_signatures'))} "
        f"负向记忆摘要来自 `NEGATIVE_MEMORY.md`：{compact(context.get('negative_memory'))} "
        f"这些内容是约束，不应把 smoke/import/clone 误读为真实进展。\n\n"
        f"最近正信号有 {len(context['positive_signals'])} 条，最近负证据有 {len(context['negative_evidence'])} 条；"
        f"evidence ledger 当前有 {context['evidence_count']} 条记录。真实实验进度为 "
        f"{context['real_experiment_progress']['observed_count']} / {context['real_experiment_progress']['target_count']}，"
        f"下一步判断是：{context['real_experiment_progress']['next_action']}。\n\n"
        f"{guidance} {cards} 当前 evidence debt / uncertainty 是：{context['uncertainty']} {user}\n"
    )


def render_en(context: dict[str, Any]) -> str:
    guidance = guidance_sentence(context, zh=False)
    cards = card_sentence(context, zh=False)
    user = user_decision_sentence(context, zh=False)
    return (
        "# CURRENT_RESEARCH_BRIEF.en\n\n"
        f"The project goal is: {context['project_goal']}. The system is `{context['state_status']}`, "
        f"the current cycle is `{context['current_cycle']}`, and the next suggested action is `{context['next_action']}`. "
        f"{('The current blocker is: ' + context['blocked_reason'] + '. ') if context.get('blocked_reason') else ''}\n\n"
        f"The main failure signatures come from `FAILURE_SIGNATURES.md`: {compact(context.get('failure_signatures'))}. "
        f"Negative memory comes from `NEGATIVE_MEMORY.md`: {compact(context.get('negative_memory'))}. "
        f"These are guardrails; smoke/import/clone evidence must not be reported as real progress.\n\n"
        f"There are {len(context['positive_signals'])} recent positive signals and {len(context['negative_evidence'])} recent negative evidence items. "
        f"The evidence ledger has {context['evidence_count']} records. Real-experiment progress is "
        f"{context['real_experiment_progress']['observed_count']} / {context['real_experiment_progress']['target_count']}; "
        f"the next interpretation is: {context['real_experiment_progress']['next_action']}.\n\n"
        f"{guidance} {cards} Current evidence debt / uncertainty: {context['uncertainty']} {user}\n"
    )


def guidance_sentence(context: dict[str, Any], *, zh: bool) -> str:
    count = len(context.get("active_guidance", []))
    if zh:
        return f"Human Idea Inbox 有 {count} 条仍需 Planner/Reviewer 处理的高优先级指导。"
    return f"The Human Idea Inbox has {count} high-priority guidance items still active for Planner/Reviewer."


def card_sentence(context: dict[str, Any], *, zh: bool) -> str:
    count = len(context.get("unconsumed_mechanism_cards", []))
    if zh:
        return f"未消费机制卡有 {count} 张，Planner 应优先把它们转成可审查 MVE。"
    return f"There are {count} unconsumed mechanism cards; Planner should prioritize turning them into reviewable MVEs."


def user_decision_sentence(context: dict[str, Any], *, zh: bool) -> str:
    count = len(context.get("user_decision_needed", []))
    if zh:
        return "当前需要用户决策。" if count else "当前没有新的用户决策阻塞。"
    return "A user decision is currently needed." if count else "No new user decision blocker is currently active."


def uncertainty_summary(open_debts: str, cards: list[dict[str, Any]], progress: dict[str, Any]) -> str:
    if open_debts.strip():
        return compact(open_debts)
    if cards:
        return "mechanism cards need metric evidence before belief can change"
    if progress.get("observed_count", 0) < progress.get("target_count", 3):
        return "more trusted real-experiment evidence is needed"
    return "no explicit open debt found; continue checking protected metrics and negative memory"


def compact(text: Any, limit: int = 240) -> str:
    value = " ".join(str(text or "").split())
    if not value:
        return "none"
    return value[:limit] + ("..." if len(value) > limit else "")


def read_text_tail(path, limit: int = 2000) -> str:
    return path.read_text()[-limit:] if path.exists() else ""


def normalize_brief_language(language: str) -> str:
    return "en" if str(language).lower().startswith("en") else "zh"
