"""Bootstrap orchestration, readiness reporting, archive, and dogfood helpers."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from . import __version__
from .adapter_onboarding import (
    activate_capability,
    adapter_discover,
    adapter_doctor,
    adapter_draft,
    adapter_init,
    adapter_lint,
    adapter_questions,
    run_contract_test,
)
from .adapter_schema import AdapterCapability, AdapterManifest, ArtifactRules, MetricsSchema, ResourcePolicy, load_adapter_manifest, write_adapter_manifest
from .discovery import discover_files, relative_files
from .io import append_jsonl, ensure_dir, next_numeric_id, read_json, read_jsonl, read_yaml, utc_now, write_json, write_text, write_yaml
from .paths import VibePaths
from .research_manager import export_research_dashboard, policy_completeness, render_daily_memo, research_init, research_readiness
from .script_bootstrap import bootstrap_script_plan, script_readiness_matrix


PHASES = ["intake", "discovery", "draft", "questions", "validation", "activation", "report"]
ISSUE_CLASSES = ["framework issue", "adapter onboarding issue", "script bootstrap issue", "policy issue", "external repo issue", "environment issue"]


def bootstrap_dir(paths: VibePaths) -> Path:
    return paths.vibe / "bootstrap"


def new_session_id(paths: VibePaths) -> str:
    sessions = bootstrap_dir(paths) / "sessions"
    existing = [path.stem for path in sessions.glob("bootstrap_*.json")] if sessions.exists() else []
    return next_numeric_id(existing, "bootstrap_")


def ensure_bootstrap_dirs(paths: VibePaths) -> None:
    ensure_dir(bootstrap_dir(paths) / "sessions")
    ensure_dir(paths.vibe / "archives")


def file_hash(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def input_hashes(paths: VibePaths) -> dict[str, str]:
    rels = [
        "README.md",
        "AGENTS.md",
        ".vibe/adapter.yaml",
        ".vibe/adapter_questions.yaml",
        ".vibe/policies/budget.yaml",
        ".vibe/policies/stage_gates.yaml",
        ".vibe/policies/autonomy.yaml",
        ".vibe/script_bootstrap_plan.md",
    ]
    return {rel: file_hash(paths.root / rel) for rel in rels}


def load_bootstrap_state(paths: VibePaths) -> dict[str, Any]:
    return read_json(bootstrap_dir(paths) / "state.json", {})


def save_bootstrap_state(paths: VibePaths, state: dict[str, Any]) -> None:
    ensure_bootstrap_dirs(paths)
    state["last_updated_at"] = utc_now()
    write_json(bootstrap_dir(paths) / "state.json", state)
    write_json(bootstrap_dir(paths) / "latest.json", {"session_id": state.get("session_id", ""), "state_path": ".vibe/bootstrap/state.json", "updated_at": state["last_updated_at"]})
    write_json(bootstrap_dir(paths) / "sessions" / f"{state.get('session_id', 'bootstrap_unknown')}.json", state)


def initial_bootstrap_state(paths: VibePaths, *, mode: str = "fresh", session_id: str | None = None) -> dict[str, Any]:
    now = utc_now()
    return {
        "session_id": session_id or new_session_id(paths),
        "repo_root": str(paths.root),
        "vibe_research_version": __version__,
        "mode": mode,
        "started_at": now,
        "last_updated_at": now,
        "current_phase": "not_started",
        "completed_phases": [],
        "blocked_phases": [],
        "failed_phases": [],
        "generated_artifacts": [],
        "question_ids": [],
        "policy_drafts": [],
        "adapter_revision": "",
        "capability_activation_status": {},
        "contract_test_summary": {},
        "readiness_level": "not_started",
        "phase_records": [],
        "input_hashes": input_hashes(paths),
        "merge_warnings": [],
    }


def bootstrap_init(paths: VibePaths, *, mode: str = "fresh", goal: str = "", background: str = "", memo_language: str = "zh-CN", autonomy_level: str = "analysis_only", force: bool = False) -> dict[str, Any]:
    paths.require_initialized()
    ensure_bootstrap_dirs(paths)
    state = initial_bootstrap_state(paths, mode=mode) if force or not load_bootstrap_state(paths) else load_bootstrap_state(paths)
    state.setdefault("bootstrap_config", {})
    state["bootstrap_config"].update({"goal": goal, "background": background, "memo_language": memo_language, "autonomy_level": autonomy_level})
    save_bootstrap_state(paths, state)
    return state


def record_phase(paths: VibePaths, state: dict[str, Any], phase: str, status: str, *, outputs: list[str] | None = None, warnings: list[str] | None = None, blockers: list[str] | None = None, next_actions: list[str] | None = None, generated_files: list[str] | None = None) -> dict[str, Any]:
    now = utc_now()
    previous = [row for row in state.get("phase_records", []) if row.get("phase") == phase]
    retry_count = len(previous)
    record = {
        "phase": phase,
        "status": status,
        "started_at": now,
        "finished_at": now,
        "input_hashes": input_hashes(paths),
        "outputs": outputs or [],
        "warnings": warnings or [],
        "blockers": blockers or [],
        "next_actions": next_actions or [],
        "retry_count": retry_count,
        "user_answers_required": [item for item in blockers or [] if "question" in item or "answer" in item],
        "generated_artifacts": generated_files or outputs or [],
        "provenance": {"source": "vibe bootstrap", "version": __version__},
    }
    state["current_phase"] = phase
    state.setdefault("phase_records", []).append(record)
    for key in ["completed_phases", "blocked_phases", "failed_phases"]:
        state.setdefault(key, [])
    for key in ["completed_phases", "blocked_phases", "failed_phases"]:
        state[key] = [item for item in state[key] if item != phase]
    if status == "passed":
        state["completed_phases"].append(phase)
    elif status == "blocked":
        state["blocked_phases"].append(phase)
    elif status == "failed":
        state["failed_phases"].append(phase)
    for artifact in record["generated_artifacts"]:
        if artifact not in state.setdefault("generated_artifacts", []):
            state["generated_artifacts"].append(artifact)
    save_bootstrap_state(paths, state)
    return record


def bootstrap_run(paths: VibePaths, *, start_phase: str | None = None, stop_after: str | None = None, non_interactive: bool = True, force: bool = False) -> dict[str, Any]:
    paths.require_initialized()
    state = load_bootstrap_state(paths) or bootstrap_init(paths)
    phases = PHASES[PHASES.index(start_phase) :] if start_phase in PHASES else PHASES
    for phase in phases:
        try:
            if phase == "intake":
                run_intake_phase(paths, state)
            elif phase == "discovery":
                run_discovery_phase(paths, state)
            elif phase == "draft":
                run_draft_phase(paths, state, force=force)
            elif phase == "questions":
                run_questions_phase(paths, state)
            elif phase == "validation":
                run_validation_phase(paths, state)
            elif phase == "activation":
                run_activation_phase(paths, state)
            elif phase == "report":
                run_report_phase(paths, state)
        except Exception as exc:
            record_phase(paths, state, phase, "failed", blockers=[str(exc)], next_actions=[f"fix {phase} failure and run vibe bootstrap resume"])
            break
        state = load_bootstrap_state(paths)
        if phase == stop_after:
            break
        if non_interactive and phase in state.get("blocked_phases", []):
            break
    return load_bootstrap_state(paths)


def bootstrap_resume(paths: VibePaths, *, non_interactive: bool = True) -> dict[str, Any]:
    state = load_bootstrap_state(paths)
    if not state:
        return bootstrap_run(paths, non_interactive=non_interactive)
    current_hashes = input_hashes(paths)
    old_hashes = state.get("input_hashes", {})
    changed = [rel for rel, value in current_hashes.items() if old_hashes.get(rel) and old_hashes.get(rel) != value]
    if changed:
        state.setdefault("merge_warnings", []).append({"created_at": utc_now(), "changed_inputs": changed, "warning": "resume detected user-edited or externally changed generated files; preserving current files"})
        state["input_hashes"] = current_hashes
        save_bootstrap_state(paths, state)
    start = first_unfinished_phase(state)
    return bootstrap_run(paths, start_phase=start, non_interactive=non_interactive, force=False)


def first_unfinished_phase(state: dict[str, Any]) -> str:
    completed = set(state.get("completed_phases", []))
    blocked = state.get("blocked_phases", [])
    failed = state.get("failed_phases", [])
    if failed:
        return failed[-1]
    if blocked:
        return blocked[-1]
    for phase in PHASES:
        if phase not in completed:
            return phase
    return "report"


def run_intake_phase(paths: VibePaths, state: dict[str, Any]) -> None:
    context = scan_context(paths)
    write_json(bootstrap_dir(paths) / "intake.json", context)
    record_phase(paths, state, "intake", "passed", outputs=[".vibe/bootstrap/intake.json"], warnings=context.get("warnings", []))


def scan_context(paths: VibePaths) -> dict[str, Any]:
    sources = []
    warnings = []
    for rel in ["README.md", "AGENTS.md", "TODO.md", "docs/README.md", "prompts/README.md"]:
        path = paths.root / rel
        if path.exists() and path.is_file():
            text = path.read_text(errors="ignore")
            sources.append({"path": rel, "sha256": hashlib.sha256(text.encode()).hexdigest()[:16], "summary": "\n".join(text.splitlines()[:80])})
    readme = (paths.root / "README.md").read_text(errors="ignore") if (paths.root / "README.md").exists() else ""
    agents = (paths.root / "AGENTS.md").read_text(errors="ignore") if (paths.root / "AGENTS.md").exists() else ""
    if implies_auto_run(readme) and requires_manual_confirmation(agents):
        warnings.append("README suggests automatic execution while AGENTS requires manual confirmation; choose conservative manual confirmation")
    return {"created_at": utc_now(), "sources": sources, "warnings": warnings, "input_hashes": input_hashes(paths)}


def implies_auto_run(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in ["auto run", "automatic", "slurm", "submit", "gpu job", "自动", "提交"])


def requires_manual_confirmation(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in ["manual confirmation", "require approval", "do not submit", "需要确认", "人工确认", "不要提交"])


def run_discovery_phase(paths: VibePaths, state: dict[str, Any]) -> None:
    report = adapter_discover(paths)
    extra = discover_project_surface(paths)
    write_json(bootstrap_dir(paths) / "discovery.json", {"adapter_discovery": report, "project_surface": extra})
    record_phase(paths, state, "discovery", "passed", outputs=[".vibe/discovery_report.json", ".vibe/bootstrap/discovery.json"], warnings=report.get("unresolved_risks", []))


def discover_project_surface(paths: VibePaths) -> dict[str, Any]:
    patterns = {
        "scripts": ["*.py", "*.sh"],
        "slurm": ["*.sbatch", "*.slurm"],
        "metrics": ["*metrics*.json", "*leaderboard*.json"],
        "logs": ["*.log", "*.out"],
        "env": ["environment.yml", "requirements.txt", "pyproject.toml", "env*.sh"],
    }
    result: dict[str, Any] = {}
    warnings: list[str] = []
    for key, globs in patterns.items():
        discovery = discover_files(paths.root, patterns=globs, max_files=80)
        warnings.extend(discovery.warnings)
        result[key] = relative_files(discovery.files, paths.root)
    result["warnings"] = sorted(set(warnings))
    return result


def run_draft_phase(paths: VibePaths, state: dict[str, Any], *, force: bool = False) -> None:
    config = state.get("bootstrap_config", {})
    adapter_init(paths, minimal=False)
    adapter_draft(paths)
    maybe_add_detected_eval_capability(paths)
    bootstrap_script_plan(paths, generate=True)
    matrix = script_readiness_matrix(paths, write=True)
    research_init(
        paths,
        goal=config.get("goal", ""),
        background=config.get("background", ""),
        memo_language=config.get("memo_language", "zh-CN"),
        autonomy_level=config.get("autonomy_level", "analysis_only"),
        force=force,
    )
    mirror_memo_config(paths)
    write_json(paths.research / "registry_init.json", {"created_at": utc_now(), "source": "vibe bootstrap draft", "status": "draft"})
    artifacts = [
        ".vibe/adapter.yaml",
        ".vibe/adapter_questions.yaml",
        ".vibe/script_bootstrap_plan.md",
        ".vibe/script_readiness.json",
        ".vibe/policies/budget.yaml",
        ".vibe/policies/stage_gates.yaml",
        ".vibe/policies/autonomy.yaml",
        ".vibe/research/research_brief.md",
        ".vibe/research/registry_init.json",
        ".vibe/memos/memo_config.yaml",
    ]
    state["policy_drafts"] = [".vibe/policies/budget.yaml", ".vibe/policies/stage_gates.yaml", ".vibe/policies/autonomy.yaml"]
    save_bootstrap_state(paths, state)
    record_phase(paths, state, "draft", "passed", outputs=artifacts, warnings=[row["status"] for row in matrix if row["status"] in {"generated_draft", "needs_user_review", "blocked_missing_project_eval"}], generated_files=artifacts)


def mirror_memo_config(paths: VibePaths) -> None:
    config = read_yaml(paths.research / "memo_config.yaml", {}) or {"language": "zh-CN", "timezone": "local"}
    write_yaml(paths.vibe / "memos" / "memo_config.yaml", config)


def maybe_add_detected_eval_capability(paths: VibePaths) -> None:
    eval_script = paths.root / "scripts" / "vibe_eval.py"
    sample_metrics = paths.root / "sample_metrics.json"
    if not eval_script.exists() and not sample_metrics.exists():
        return
    manifest = load_adapter_manifest(paths)
    if any(cap.id == "evaluation_smoke" and cap.metrics_schema.required for cap in manifest.capabilities):
        return
    caps = [cap for cap in manifest.capabilities if cap.id != "evaluation_smoke"]
    command = "python scripts/vibe_eval.py --metrics-out .vibe/bootstrap_metrics/evaluation_smoke.json --dryrun" if eval_script.exists() else "python .vibe/scripts/evaluation_smoke.py --dryrun"
    caps.append(
        AdapterCapability(
            id="evaluation_smoke",
            version="bootstrap-draft",
            status="draft",
            task_type="evaluation_smoke",
            supported_decisions=["collect_more_metrics"],
            description="Bootstrap-detected low-risk evaluation smoke capability.",
            dryrun={"command": command},
            entrypoint={"type": "local", "command": command.replace(" --dryrun", " --smoke")},
            outputs={"expected_output_path": ".vibe/bootstrap_metrics/evaluation_smoke.json", "metrics_file_path": ".vibe/bootstrap_metrics/evaluation_smoke.json"},
            metrics_schema=MetricsSchema(required=["primary"], types={"primary": "number"}, primary_metric="primary", version="bootstrap"),
            artifact_rules=ArtifactRules(expected_outputs=[".vibe/bootstrap_metrics/evaluation_smoke.json"], trusted_path_patterns=[".vibe/bootstrap_metrics/*.json"], version="bootstrap"),
            resources=ResourcePolicy(automatic_submission_allowed=False, user_confirmation_required=False, default={"gpu": 0, "cpus": 1, "mem_gb": 1, "time": "00:05:00"}),
            trust_checks=["schema_valid_metrics", "expected_output_exists"],
            contract_tests=["evaluation_smoke"],
            provenance={"source": "bootstrap detected eval/sample metrics", "created_at": utc_now()},
        )
    )
    manifest.capabilities = caps
    write_adapter_manifest(paths, manifest)


def run_questions_phase(paths: VibePaths, state: dict[str, Any]) -> None:
    blockers = []
    question_ids = []
    manifest = load_adapter_manifest(paths)
    for question in manifest.open_questions:
        question_ids.append(question.id)
        if question.severity == "blocker" and not question.confirmed:
            blockers.append(f"answer adapter question {question.id}")
    completeness = policy_completeness(paths)
    for issue in completeness.get("issues", []):
        blockers.append(f"policy question required: {issue}")
    conflicts = scan_context(paths).get("warnings", [])
    for warning in conflicts:
        qid = "q_readme_agents_conflict"
        question_ids.append(qid)
        append_jsonl(paths.research / "questions.jsonl", {"question_id": qid, "status": "open", "question": warning, "created_at": utc_now(), "severity": "blocker"})
        blockers.append("answer README/AGENTS conflict question")
    state["question_ids"] = sorted(set(question_ids))
    save_bootstrap_state(paths, state)
    status = "blocked" if blockers else "passed"
    record_phase(paths, state, "questions", status, outputs=[".vibe/adapter_questions.yaml", ".vibe/research/questions.jsonl"], blockers=blockers, next_actions=["answer blocker questions and run vibe bootstrap resume"] if blockers else [])


def run_validation_phase(paths: VibePaths, state: dict[str, Any]) -> None:
    lint = adapter_lint(paths)
    manifest = load_adapter_manifest(paths)
    contract_summary: dict[str, Any] = {}
    blockers = []
    for cap in manifest.capabilities:
        if cap.status in {"draft", "candidate"} and cap.dryrun.get("command") and (cap.metrics_schema.required or cap.metrics_schema.types):
            result = run_contract_test(paths, cap.id)
            contract_summary[cap.id] = result
            if result.get("status") != "passed":
                blockers.append(f"contract failed for {cap.id}")
    completeness = policy_completeness(paths)
    if not lint.get("ok"):
        blockers.append("adapter lint failed")
    blockers.extend(completeness.get("issues", []))
    state["contract_test_summary"] = contract_summary
    save_bootstrap_state(paths, state)
    record_phase(paths, state, "validation", "blocked" if blockers else "passed", outputs=[".vibe/adapter_lint.json", ".vibe/contract_tests"], blockers=blockers, next_actions=["fix validation blockers and run vibe bootstrap resume"] if blockers else [])


def run_activation_phase(paths: VibePaths, state: dict[str, Any]) -> None:
    manifest = load_adapter_manifest(paths)
    activation = {}
    warnings = []
    for cap in manifest.capabilities:
        contract = read_json(paths.vibe / "contract_tests" / f"{cap.id}.json", {})
        if cap.status in {"draft", "candidate"} and contract.get("status") == "passed":
            try:
                activate_capability(paths, cap.id, user_confirmation="bootstrap contract passed")
                activation[cap.id] = "active"
            except Exception as exc:
                activation[cap.id] = "requires_user_answer"
                warnings.append(str(exc))
        elif cap.status == "active":
            activation[cap.id] = "active"
        elif cap.status.startswith("blocked_"):
            activation[cap.id] = cap.status
    state["capability_activation_status"] = activation
    save_bootstrap_state(paths, state)
    record_phase(paths, state, "activation", "passed" if any(value == "active" for value in activation.values()) else "blocked", outputs=[".vibe/adapter.yaml"], warnings=warnings, blockers=[] if any(value == "active" for value in activation.values()) else ["no capability activated"], next_actions=["answer blockers or run contract tests before activation"] if not any(value == "active" for value in activation.values()) else [])


def run_report_phase(paths: VibePaths, state: dict[str, Any]) -> None:
    readiness = build_readiness(paths)
    write_json(bootstrap_dir(paths) / "readiness.json", readiness)
    write_text(bootstrap_dir(paths) / "readiness_report.md", render_readiness_report(readiness))
    render_daily_memo(paths)
    export_readiness_dashboard(paths)
    state["readiness_level"] = readiness["readiness_level"]
    save_bootstrap_state(paths, state)
    record_phase(paths, state, "report", "passed", outputs=[".vibe/bootstrap/readiness.json", ".vibe/bootstrap/readiness_report.md", ".vibe/memos", ".vibe/dashboard/readiness_export.json"])


def build_readiness(paths: VibePaths) -> dict[str, Any]:
    adapter = adapter_doctor(paths)
    completeness = policy_completeness(paths)
    scripts = script_readiness_matrix(paths, write=True)
    state = load_bootstrap_state(paths)
    active = adapter.get("active_capabilities", [])
    readiness_level = "real_experiment_ready" if adapter.get("ready_for_real_experiments") and completeness.get("safe_for_low_risk_execution") else "instrumentation_ready" if adapter.get("ready_for_instrumentation") and completeness.get("safe_for_low_risk_execution") else "blocked" if state.get("blocked_phases") else "draft"
    allowed = {
        "instrumentation": adapter.get("ready_for_instrumentation", False) and completeness.get("safe_for_low_risk_execution", False),
        "evaluation": adapter.get("ready_for_evaluation", False) and completeness.get("safe_for_low_risk_execution", False),
        "training_gate": adapter.get("ready_for_training", False) and completeness.get("complete", False),
        "long_run": adapter.get("ready_for_long_run", False) and completeness.get("complete", False),
        "bounded_continuous": adapter.get("ready_for_real_experiments", False) and completeness.get("complete", False) and research_readiness(paths).get("ready_for_bounded_autonomy", False),
    }
    next_actions = []
    if adapter.get("next_blockers"):
        next_actions.extend(adapter["next_blockers"][:5])
    if completeness.get("issues"):
        next_actions.extend(completeness["issues"][:5])
    if not next_actions:
        next_actions.append("run vibe memory build or create the first hypothesis")
    return {
        "created_at": utc_now(),
        "readiness_level": readiness_level,
        "statuses": {"bootstrap": explicit_bootstrap_status(state), "adapter": adapter, "policy_completeness": completeness, "script_readiness": scripts},
        "active_capabilities": active,
        "blocked_capabilities": adapter.get("blocked_capabilities", []),
        "incomplete_policies": completeness.get("issues", []),
        "required_questions": adapter.get("missing_user_answers", []),
        "generated_scripts_not_validated": [row for row in scripts if row["status"] in {"generated_draft", "needs_user_review", "blocked_missing_project_eval"}],
        "contract_test_failures": sorted(
            set(adapter.get("contract_failures", []))
            | {row.get("capability_id", "") for row in adapter.get("contract_tests", []) if row.get("status") == "failed"}
        ),
        "allowed_actions": allowed,
        "smallest_actionable_next_step": next_actions[0],
        "next_actions": next_actions,
    }


def explicit_bootstrap_status(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "session_id": state.get("session_id", ""),
        "current_phase": state.get("current_phase", "not_started"),
        "completed_phases": state.get("completed_phases", []),
        "blocked_phases": state.get("blocked_phases", []),
        "failed_phases": state.get("failed_phases", []),
        "merge_warnings": state.get("merge_warnings", []),
    }


def render_readiness_report(readiness: dict[str, Any]) -> str:
    lines = [
        "# Bootstrap Readiness Report",
        "",
        f"Readiness level: `{readiness['readiness_level']}`",
        f"Smallest next step: {readiness['smallest_actionable_next_step']}",
        "",
        "## Active Capabilities",
        "",
    ]
    lines.extend(f"- `{cap}`" for cap in readiness.get("active_capabilities", [])) or lines.append("- none")
    lines.extend(["", "## Blocked Capabilities", ""])
    lines.extend(f"- `{cap}`" for cap in readiness.get("blocked_capabilities", [])) or lines.append("- none")
    lines.extend(["", "## Incomplete Policies", ""])
    lines.extend(f"- {item}" for item in readiness.get("incomplete_policies", [])) or lines.append("- none")
    lines.extend(["", "## Generated Scripts Not Yet Validated", ""])
    scripts = readiness.get("generated_scripts_not_validated", [])
    lines.extend(f"- `{row['id']}` {row['status']}" for row in scripts) or lines.append("- none")
    lines.extend(["", "## Allowed Automation", ""])
    for key, value in readiness.get("allowed_actions", {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Next Actions", ""])
    lines.extend(f"- {item}" for item in readiness.get("next_actions", []))
    return "\n".join(lines) + "\n"


def export_readiness_dashboard(paths: VibePaths) -> dict[str, Any]:
    readiness = read_json(bootstrap_dir(paths) / "readiness.json", {}) or build_readiness(paths)
    memos = []
    if (paths.vibe / "memos").exists():
        for path in sorted((paths.vibe / "memos").glob("*.json")):
            memos.append({"date": path.stem, "path": str(path.relative_to(paths.root)), "status": "passed"})
    dogfood = read_json(bootstrap_dir(paths) / "dogfood_report.json", {})
    export_research_dashboard(paths)
    data = {
        "adapter_readiness": readiness.get("statuses", {}).get("adapter", {}),
        "bootstrap_state": load_bootstrap_state(paths),
        "policy_completeness": readiness.get("statuses", {}).get("policy_completeness", {}),
        "script_readiness": readiness.get("statuses", {}).get("script_readiness", []),
        "contract_test_summary": load_bootstrap_state(paths).get("contract_test_summary", {}),
        "dogfood_report": dogfood,
        "research_registry_summary": read_json(paths.dashboard / "research_registry.json", {}),
        "daily_memo_index": memos,
        "statuses": ["not_started", "running", "blocked", "failed", "passed", "active", "draft", "untrusted", "imported_unverified", "requires_user_answer"],
    }
    write_json(paths.dashboard / "readiness_export.json", data)
    return data


def bootstrap_status(paths: VibePaths) -> dict[str, Any]:
    return {"state": load_bootstrap_state(paths), "readiness": build_readiness(paths)}


def archive_legacy(paths: VibePaths, *, source: Path | None = None, note: str = "") -> dict[str, Any]:
    paths.require_initialized()
    source_root = source.expanduser().resolve() if source else paths.root
    archive_id = utc_now().replace(":", "").replace("-", "")
    archive_dir = ensure_dir(paths.vibe / "archives" / archive_id)
    candidates = []
    for rel in [".vibe", "VIBE_TIMELINE.md", "VIBE_STATUS.md", "VIBE_TODO.md", "VIBE_LEADERBOARD.md", "RUN.md", "Problem.md", "prompts/v0.6.0-problem.md", "results", "AUTO_RESEARCH_PROGRESS"]:
        candidate = source_root / rel
        if candidate.exists():
            candidates.append(candidate)
    files = []
    for candidate in candidates:
        if candidate.is_file():
            files.append(index_file(source_root, candidate))
        else:
            discovered = discover_files(candidate, rel_root=source_root, max_files=max(1, 2000 - len(files)), max_seconds=8.0)
            for path in discovered.files:
                files.append(index_file(source_root, path))
            if discovered.warnings:
                files.append({"path": str(candidate.relative_to(source_root)), "size": 0, "sha256": "", "status": "truncated", "warnings": discovered.warnings})
    summary = regression_summary_from_index(source_root, files)
    manifest = {"archive_id": archive_id, "created_at": utc_now(), "source_root": str(source_root), "note": note, "files": files[:2000], "file_count": len(files), "failure_summary": summary, "trust_status": "historical_context_only"}
    write_json(archive_dir / "manifest.json", manifest)
    write_text(archive_dir / "failure_summary.md", render_failure_summary(summary))
    return manifest


def index_file(source_root: Path, path: Path) -> dict[str, Any]:
    rel = str(path.relative_to(source_root))
    return {"path": rel, "size": path.stat().st_size, "sha256": file_hash(path), "status": "indexed"}


def regression_summary_from_index(source_root: Path, files: list[dict[str, Any]]) -> dict[str, Any]:
    cases = []
    for row in files:
        rel = row["path"]
        if not any(token in rel.lower() for token in ["timeline", "leaderboard", "metrics", "problem", "result"]):
            continue
        path = source_root / rel
        if not path.exists() or path.stat().st_size > 2_000_000:
            continue
        text = path.read_text(errors="ignore").lower()
        if "primary=0.0" in text or '"primary_metric": 0' in text or "blocked_repeating_evidence" in text or "continued exploration" in text or "collect_more_metrics" in text:
            cases.append({"path": rel, "status": "imported_unverified", "regression_case": "possible_fake_progress_or_repeating_evidence"})
    return {"regression_cases": cases[:100], "import_status": "imported_unverified"}


def render_failure_summary(summary: dict[str, Any]) -> str:
    lines = ["# Legacy Failure Summary", "", "Imported legacy evidence is historical context only and defaults to `imported_unverified`.", ""]
    for row in summary.get("regression_cases", []):
        lines.append(f"- `{row['path']}` {row['regression_case']}")
    if not summary.get("regression_cases"):
        lines.append("- no fake-progress pattern detected")
    return "\n".join(lines) + "\n"


def import_legacy(paths: VibePaths, archive_manifest: Path) -> dict[str, Any]:
    manifest = read_json(archive_manifest, {})
    if not manifest:
        raise ValueError(f"missing archive manifest: {archive_manifest}")
    imported = {"created_at": utc_now(), "source_archive": str(archive_manifest), "status": "imported_unverified", "items": manifest.get("failure_summary", {}).get("regression_cases", [])}
    write_json(paths.research / "legacy_import.json", imported)
    append_jsonl(paths.research / "events.jsonl", {"event_id": "legacy_import", "event_type": "legacy_imported", "created_at": utc_now(), "payload": imported})
    return imported


def ensure_dogfood_ignore(root: Path) -> None:
    gitignore = root / ".gitignore"
    text = gitignore.read_text() if gitignore.exists() else ""
    if ".vibe_dogfood/" not in text:
        if text and not text.endswith("\n"):
            text += "\n"
        text += "\n# Local VibeResearch bootstrap dogfood sandboxes\n.vibe_dogfood/\n"
        write_text(gitignore, text)


def create_local_dogfood_profile(root: Path, profile: str) -> Path:
    ensure_dogfood_ignore(root)
    target = root / ".vibe_dogfood" / profile
    if target.exists():
        shutil.rmtree(target)
    ensure_dir(target)
    write_text(target / "README.md", dogfood_readme(profile))
    write_text(target / "AGENTS.md", dogfood_agents(profile))
    ensure_dir(target / "scripts")
    if "happy-path" in profile or "resume-after-failure" in profile:
        write_eval_script(target / "scripts" / "vibe_eval.py")
        write_text(target / "sample_metrics.json", json.dumps({"primary": 1.0}) + "\n")
        write_yaml(target / ".vibe_bootstrap_answers.yaml", {"confirm_all_adapter_questions": True})
    elif "placeholder-script" in profile:
        write_text(target / "scripts" / "vibe_eval.py", "print('placeholder')\n")
        write_yaml(target / ".vibe_bootstrap_answers.yaml", {"confirm_all_adapter_questions": True})
    elif "policy-conflict" in profile:
        write_eval_script(target / "scripts" / "vibe_eval.py")
        write_text(target / "sample_metrics.json", json.dumps({"primary": 1.0}) + "\n")
    return target


def dogfood_readme(profile: str) -> str:
    text = "# Dogfood Toy Repo\n\nThis repo exercises VibeResearch bootstrap.\n"
    if "policy-conflict" in profile:
        text += "\nREADME says automatic Slurm/GPU submit is allowed for smoke jobs.\n"
    return text


def dogfood_agents(profile: str) -> str:
    text = "# Agent Notes\n\nUse Chinese reports. Do not run high-cost jobs without manual confirmation.\n"
    if "policy-conflict" in profile:
        text += "Manual confirmation is required before any automatic Slurm or GPU submission.\n"
    return text


def write_eval_script(path: Path) -> None:
    write_text(
        path,
        """#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--metrics-out", default=".vibe/bootstrap_metrics/evaluation_smoke.json")
parser.add_argument("--dryrun", action="store_true")
parser.add_argument("--smoke", action="store_true")
args = parser.parse_args()
out = Path(args.metrics_out)
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps({"primary": 1.0, "mode": "dryrun" if args.dryrun else "smoke"}) + "\\n")
""",
    )
    try:
        path.chmod(0o755)
    except OSError:
        pass


def apply_bootstrap_answers(paths: VibePaths) -> None:
    answers = read_yaml(paths.root / ".vibe_bootstrap_answers.yaml", {}) or {}
    if answers.get("confirm_all_adapter_questions"):
        manifest = load_adapter_manifest(paths)
        for question in manifest.open_questions:
            question.current_answer = "confirmed by dogfood bootstrap answers"
            question.confirmed = True
            question.answer_source = ".vibe_bootstrap_answers.yaml"
            question.updated_at = utc_now()
        write_adapter_manifest(paths, manifest)
        write_yaml(paths.vibe / "adapter_questions.yaml", {"questions": [q.model_dump() for q in manifest.open_questions]})


def run_dogfood(paths: VibePaths, *, profile: str = "0.8.6-happy-path", external_repo: Path | None = None, brief_file: Path | None = None, output_report: Path | None = None, dry_run: bool = False) -> dict[str, Any]:
    repo = external_repo.expanduser().resolve() if external_repo else create_local_dogfood_profile(paths.root, profile)
    report_path = output_report or (bootstrap_dir(paths) / "dogfood_report.json")
    issues: list[dict[str, Any]] = []
    phase_results: list[dict[str, Any]] = []
    if external_repo and dry_run:
        context = scan_external_repo(repo)
        if brief_file:
            brief = brief_file.expanduser().resolve()
            context["brief_file"] = {"path": str(brief), "sha256": file_hash(brief), "summary": brief.read_text(errors="ignore")[:2000] if brief.exists() else ""}
        readiness = {"readiness_level": "dry_run_external_inspection", "context": context}
        if not context.get("readme"):
            issues.append({"class": "external repo issue", "message": "README not found"})
        if context.get("legacy_vibe"):
            issues.append({"class": "adapter onboarding issue", "message": "legacy .vibe exists; archive or rename before fresh bootstrap"})
        result = {"created_at": utc_now(), "profile": profile, "repo": str(repo), "dry_run": True, "phase_results": [{"phase": "external_inspection", "status": "passed"}], "issues": issues, "readiness": readiness, "issue_classes": ISSUE_CLASSES}
        write_json(report_path, result)
        write_json(bootstrap_dir(paths) / "dogfood_report.json", result)
        return result
    target_paths = VibePaths(repo)
    if not target_paths.vibe.exists():
        from .project import init_project

        init_project(repo, goal="Dogfood bootstrap validation", background=f"Profile {profile}", root_portal="none")
    bootstrap_init(target_paths, goal="Dogfood bootstrap validation", background=f"Profile {profile}", memo_language="zh-CN", autonomy_level="bounded_continuous", force=True)
    state = bootstrap_run(target_paths, stop_after="draft", non_interactive=False, force=True)
    apply_bootstrap_answers(target_paths)
    state = bootstrap_run(target_paths, start_phase="questions", non_interactive=False, force=False)
    readiness = read_json(bootstrap_dir(target_paths) / "readiness.json", {}) or build_readiness(target_paths)
    for record in state.get("phase_records", []):
        phase_results.append({"phase": record.get("phase"), "status": record.get("status"), "blockers": record.get("blockers", [])})
        for blocker in record.get("blockers", []):
            issues.append(classify_issue(blocker))
    result = {"created_at": utc_now(), "profile": profile, "repo": str(repo), "dry_run": dry_run, "phase_results": phase_results, "issues": issues, "readiness": readiness, "issue_classes": ISSUE_CLASSES}
    write_json(report_path, result)
    write_json(bootstrap_dir(paths) / "dogfood_report.json", result)
    return result


def scan_external_repo(repo: Path) -> dict[str, Any]:
    scripts = discover_files(repo, patterns=["*.py"], max_files=50)
    return {
        "repo": str(repo),
        "readme": (repo / "README.md").exists(),
        "agents": (repo / "AGENTS.md").exists(),
        "legacy_vibe": (repo / ".vibe").exists(),
        "results": (repo / "results").exists(),
        "candidate_scripts": relative_files(scripts.files, repo),
        "discovery_warnings": scripts.warnings,
        "legacy_files": [name for name in ["VIBE_STATUS.md", "VIBE_TIMELINE.md", "VIBE_LEADERBOARD.md", "AUTO_RESEARCH_PROGRESS"] if (repo / name).exists()],
    }


def classify_issue(message: str) -> dict[str, Any]:
    lowered = message.lower()
    if "policy" in lowered:
        cls = "policy issue"
    elif "contract" in lowered or "script" in lowered:
        cls = "script bootstrap issue"
    elif "adapter" in lowered or "capability" in lowered:
        cls = "adapter onboarding issue"
    elif "environment" in lowered or "permission" in lowered:
        cls = "environment issue"
    else:
        cls = "framework issue"
    return {"class": cls, "message": message}
