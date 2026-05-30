"""Adapter onboarding lifecycle commands and readiness reporting."""

from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .adapter_schema import (
    AdapterCapability,
    AdapterManifest,
    AdapterQuestion,
    ArtifactRules,
    MetricsSchema,
    ResourcePolicy,
    adapter_path,
    compute_revision,
    derive_maturity,
    hash_dict,
    lint_adapter,
    load_adapter_manifest,
    write_adapter_manifest,
)
from .adapters import is_placeholder_command
from .discovery import discover_files, relative_files
from .io import append_jsonl, ensure_dir, read_json, read_yaml, utc_now, write_json, write_text, write_yaml
from .paths import VibePaths
from .real_experiments import EVALUATION_TASKS, INSTRUMENTATION_TASKS, LONG_RUN_TASKS, REAL_EXPERIMENT_TASKS, TRAINING_TASKS
from .script_bootstrap import bootstrap_script_plan, wrapper_inventory
from .timeline import record_event


QUESTION_TEMPLATES = [
    ("q_primary_metric", "What is the primary metric?", "primary metric is required for trusted evidence", "metrics_schema.primary_metric"),
    ("q_data_path", "Where is the trusted data path?", "data access must be explicit before scripts can be trusted", "inputs.data_path"),
    ("q_baseline", "Where is the trusted baseline or baseline registry?", "baseline comparison requires trusted baseline provenance", "baseline_notes"),
    ("q_gpu_permission", "May VibeResearch submit automatic GPU jobs?", "resource policy must not silently assume GPU permission", "resources.automatic_submission_allowed"),
    ("q_metrics_format", "What metrics file format and required keys should wrappers produce?", "metrics export schema must be confirmed", "metrics_schema.required"),
    ("q_trusted_outputs", "Which output paths can be treated as trusted artifacts?", "artifact trust rules are required for promotion", "artifact_rules.trusted_path_patterns"),
]


def adapter_init(paths: VibePaths, *, minimal: bool = False, script_dir: str = ".vibe/scripts") -> dict[str, Any]:
    ensure_adapter_dirs(paths)
    manifest = load_adapter_manifest(paths)
    if not manifest.project_id:
        manifest.project_id = paths.root.name
    if not manifest.project_name:
        manifest.project_name = paths.root.name
    manifest.adapter_version = "0.7.1"
    manifest.provenance.setdefault("created_by", "vibe adapter init")
    manifest.provenance["updated_at"] = utc_now()
    if not manifest.open_questions:
        manifest.open_questions = default_questions()
    if not manifest.capabilities and not minimal:
        manifest.capabilities = default_draft_capabilities(script_dir)
    write_adapter_manifest(paths, manifest)
    write_yaml(paths.vibe / "adapter_questions.yaml", {"questions": [q.model_dump() for q in manifest.open_questions]})
    write_text(paths.vibe / "research_brief.md", research_brief_template(paths))
    write_text(paths.vibe / "discovery_report.md", "# Adapter Discovery Report\n\nDiscovery has not run yet.\n")
    write_json(paths.vibe / "discovery_report.json", {"status": "not_run", "created_at": utc_now()})
    write_text(paths.vibe / "adapter_gitignore_suggestion.md", adapter_gitignore_suggestion())
    bootstrap_script_plan(paths, script_dir=script_dir, generate=not minimal)
    ensure_dir(paths.vibe / "contract_tests")
    ensure_dir(paths.vibe / "run_contracts")
    if not (paths.vibe / "adapter_history.jsonl").exists():
        write_text(paths.vibe / "adapter_history.jsonl", "")
    append_jsonl(paths.vibe / "adapter_history.jsonl", {"event": "adapter_initialized", "minimal": minimal, "created_at": utc_now(), "adapter_revision": manifest.adapter_revision})
    record_event(paths, "adapter_initialized", "Initialized adapter onboarding workspace", status="minimal" if minimal else "draft")
    if minimal:
        set_adapter_block(paths, "adapter/script bootstrap is incomplete; run vibe adapter init or vibe adapter doctor")
    return adapter_readiness(paths)


def ensure_adapter_dirs(paths: VibePaths) -> None:
    for rel in ["contract_tests", "run_contracts"]:
        ensure_dir(paths.vibe / rel)


def research_brief_template(paths: VibePaths) -> str:
    return f"""# Research Brief

Project: `{paths.root.name}`

## Objective
Fill in the downstream project objective and acceptance criteria.

## Constraints
Document data access, baseline, metrics, trusted outputs, and resource limits.
"""


def adapter_gitignore_suggestion() -> str:
    return """# Adapter Gitignore Suggestions

Keep adapter contracts, questions, doctor reports, and reviewed wrapper scripts
under version control when they describe project behavior. Ignore local-only
runtime output such as:

```gitignore
.vibe/bootstrap_metrics/
.vibe/run_contracts/
.vibe/runtime/env/
.vibe/config.local.yaml
.vibe/config.detected.yaml
```
"""


def default_questions() -> list[AdapterQuestion]:
    now = utc_now()
    return [
        AdapterQuestion(id=qid, question=question, why_needed=why, blocks_field=field, created_at=now, updated_at=now)
        for qid, question, why, field in QUESTION_TEMPLATES
    ]


def default_draft_capabilities(script_dir: str = ".vibe/scripts") -> list[AdapterCapability]:
    caps = []
    for task in ["environment_probe", "data_probe", "baseline_inventory", "evaluation_smoke", "metrics_export"]:
        low_risk = task in {"environment_probe", "data_probe", "baseline_inventory"}
        cap = AdapterCapability(
            id=task,
            version="draft",
            status="draft" if low_risk else "blocked_missing_metrics_schema",
            task_type=task,
            supported_decisions=["collect_more_metrics"] if task in {"evaluation_smoke", "metrics_export"} else [],
            description=f"Draft {task} wrapper generated for adapter onboarding.",
            dryrun={"command": f"python {script_dir}/{task}.py --dryrun"},
            entrypoint={"type": "local", "command": f"python {script_dir}/{task}.py --smoke"},
            outputs={"expected_output_path": f".vibe/bootstrap_metrics/{task}.json", "metrics_file_path": f".vibe/bootstrap_metrics/{task}.json"},
            metrics_schema=MetricsSchema(required=["primary"], types={"primary": "number"}, primary_metric="primary", version="bootstrap-draft") if low_risk else MetricsSchema(),
            artifact_rules=ArtifactRules(expected_outputs=[f".vibe/bootstrap_metrics/{task}.json"], trusted_path_patterns=[".vibe/bootstrap_metrics/*.json"], required_files=[], version="bootstrap-draft" if low_risk else "draft"),
            resources=ResourcePolicy(automatic_submission_allowed=False, user_confirmation_required=not low_risk),
            trust_checks=["schema_valid_metrics", "expected_output_exists"],
            contract_tests=[task],
            provenance={"source": "adapter bootstrap", "script_dir": script_dir, "created_at": utc_now()},
        )
        caps.append(cap)
    for task, decision in [("baseline_compare", "promote_to_baseline_compare"), ("train_smoke", "launch_gpu_gate"), ("train_gate", "launch_gpu_gate"), ("long_run_submit", "launch_gpu_gate")]:
        caps.append(
            AdapterCapability(
                id=task,
                version="draft",
                status="blocked_missing_user_answer" if task == "long_run_submit" else "blocked_missing_script",
                task_type=task,
                supported_decisions=[decision],
                description=f"Candidate {task} capability; script and trust policy must be supplied by the downstream repo.",
                provenance={"source": "adapter bootstrap", "created_at": utc_now()},
            )
        )
    return caps


def adapter_discover(paths: VibePaths) -> dict[str, Any]:
    warnings: list[str] = []
    scripts = find_extensions_with_warnings(paths.root, [".py", ".sh"], max_count=100, warnings=warnings)
    configs = find_extensions_with_warnings(paths.root, [".yaml", ".yml", ".json", ".toml"], max_count=80, warnings=warnings)
    notebooks = find_extensions_with_warnings(paths.root, [".ipynb"], max_count=30, warnings=warnings)
    slurm = find_globs_with_warnings(paths.root, ["*.sbatch", "*.slurm"], warnings=warnings)
    metrics = find_globs_with_warnings(paths.root, ["*metrics*.json", "*metric*.json", "*leaderboard*.json"], warnings=warnings)
    candidates = {
        "readmes": find_by_names(paths.root, ["README.md", "README.rst", "README.txt"]),
        "docs": find_dirs(paths.root, ["docs", "doc"]),
        "scripts": scripts,
        "configs": configs,
        "tests": find_dirs(paths.root, ["tests", "test"]),
        "slurm": slurm,
        "notebooks": notebooks,
        "metrics_files": metrics,
        "requirements": find_by_names(paths.root, ["requirements.txt", "environment.yml", "pyproject.toml", "setup.py"]),
    }
    risks = []
    if not candidates["metrics_files"]:
        risks.append("No candidate metrics files found; metrics schema must be supplied.")
    if not candidates["scripts"]:
        risks.append("No candidate scripts found; wrapper bootstrap remains draft.")
    report = {"created_at": utc_now(), "candidates": candidates, "unresolved_risks": risks, "discovery_warnings": sorted(set(warnings))}
    write_json(paths.vibe / "discovery_report.json", report)
    lines = ["# Adapter Discovery Report", ""]
    for key, values in candidates.items():
        lines.extend([f"## {key}", ""])
        lines.extend(f"- `{value}`" for value in values[:40])
        if not values:
            lines.append("- none")
        lines.append("")
    lines.extend(["## Unresolved Risks", ""])
    lines.extend(f"- {risk}" for risk in risks) if risks else lines.append("- none")
    lines.extend(["", "## Discovery Warnings", ""])
    lines.extend(f"- {warning}" for warning in sorted(set(warnings))) if warnings else lines.append("- none")
    write_text(paths.vibe / "discovery_report.md", "\n".join(lines) + "\n")
    append_jsonl(paths.vibe / "adapter_history.jsonl", {"event": "adapter_discovered", "created_at": utc_now(), "risk_count": len(risks)})
    record_event(paths, "adapter_discovered", f"Discovery risks={len(risks)}", status="recorded", payload=report)
    return report


def find_by_names(root: Path, names: list[str]) -> list[str]:
    found = []
    for name in names:
        path = root / name
        if path.exists():
            found.append(str(path.relative_to(root)))
    return found


def find_dirs(root: Path, names: list[str]) -> list[str]:
    return [str((root / name).relative_to(root)) for name in names if (root / name).is_dir()]


def find_extensions(root: Path, suffixes: list[str], *, max_count: int) -> list[str]:
    return find_extensions_with_warnings(root, suffixes, max_count=max_count, warnings=[])


def find_extensions_with_warnings(root: Path, suffixes: list[str], *, max_count: int, warnings: list[str]) -> list[str]:
    result = discover_files(root, patterns=["*" + suffix for suffix in suffixes], max_files=max_count)
    warnings.extend(result.warnings)
    return relative_files(result.files, root)


def find_globs(root: Path, patterns: list[str]) -> list[str]:
    return find_globs_with_warnings(root, patterns, warnings=[])


def find_globs_with_warnings(root: Path, patterns: list[str], *, warnings: list[str]) -> list[str]:
    result = discover_files(root, patterns=patterns, max_files=80)
    warnings.extend(result.warnings)
    return relative_files(result.files, root)


def adapter_draft(paths: VibePaths) -> AdapterManifest:
    manifest = load_adapter_manifest(paths)
    report = read_json(paths.vibe / "discovery_report.json", {})
    if not manifest.capabilities:
        manifest.capabilities = default_draft_capabilities()
    if report.get("candidates", {}).get("metrics_files"):
        for cap in manifest.capabilities:
            if cap.id == "metrics_export" and cap.status == "blocked_missing_metrics_schema":
                cap.status = "draft"
                cap.owner_notes = "Discovery found candidate metrics files; confirm schema before activation."
    if not manifest.open_questions:
        manifest.open_questions = default_questions()
    manifest.provenance["drafted_at"] = utc_now()
    write_adapter_manifest(paths, manifest)
    write_yaml(paths.vibe / "adapter_questions.yaml", {"questions": [q.model_dump() for q in manifest.open_questions]})
    append_jsonl(paths.vibe / "adapter_history.jsonl", {"event": "adapter_drafted", "created_at": utc_now(), "adapter_revision": manifest.adapter_revision})
    record_event(paths, "adapter_drafted", "Updated draft adapter manifest", status="draft")
    return manifest


def adapter_questions(paths: VibePaths, *, answer: tuple[str, str] | None = None, confirm: bool = False) -> list[dict[str, Any]]:
    manifest = load_adapter_manifest(paths)
    if answer:
        qid, value = answer
        for question in manifest.open_questions:
            if question.id == qid:
                question.current_answer = value
                question.answer_source = "operator_cli"
                question.confirmed = confirm
                question.updated_at = utc_now()
    write_adapter_manifest(paths, manifest)
    write_yaml(paths.vibe / "adapter_questions.yaml", {"questions": [q.model_dump() for q in manifest.open_questions]})
    return [q.model_dump() for q in manifest.open_questions]


def adapter_lint(paths: VibePaths) -> dict[str, Any]:
    result = lint_adapter(paths)
    write_json(paths.vibe / "adapter_lint.json", result)
    append_jsonl(paths.vibe / "adapter_history.jsonl", {"event": "adapter_linted", "created_at": utc_now(), **result})
    record_event(paths, "adapter_linted", "Adapter lint " + ("passed" if result["ok"] else "failed"), status="ok" if result["ok"] else "failed", payload=result)
    return result


def adapter_doctor(paths: VibePaths) -> dict[str, Any]:
    readiness = adapter_readiness(paths)
    write_real_experiment_gap_report(paths, readiness)
    lines = [
        "# Adapter Doctor",
        "",
        f"Maturity level: `{readiness['maturity_level']}`",
        f"Adapter revision: `{readiness.get('adapter_revision', '')}`",
        f"Ready for instrumentation: `{readiness['ready_for_instrumentation']}`",
        f"Ready for real experiments: `{readiness['ready_for_real_experiments']}`",
        f"Ready for Slurm-backed real experiments: `{readiness['ready_for_slurm_real_experiments']}`",
        "",
        "## Active Capabilities",
        "",
    ]
    lines.extend(f"- `{cap}`" for cap in readiness["active_capabilities"]) if readiness["active_capabilities"] else lines.append("- none")
    lines.extend(["", "## Draft/Candidate Capabilities", ""])
    lines.extend(f"- `{cap}`" for cap in readiness["draft_capabilities"]) if readiness["draft_capabilities"] else lines.append("- none")
    lines.extend(["", "## Blocked Capabilities", ""])
    lines.extend(f"- `{cap}`" for cap in readiness["blocked_capabilities"]) if readiness["blocked_capabilities"] else lines.append("- none")
    lines.extend(["", "## Blocked Real Experiment Capabilities", ""])
    lines.extend(f"- `{cap}`" for cap in readiness["blocked_real_experiment_capabilities"]) if readiness["blocked_real_experiment_capabilities"] else lines.append("- none")
    lines.extend(["", "## Missing Scripts", ""])
    lines.extend(f"- {item}" for item in readiness["missing_scripts"]) if readiness["missing_scripts"] else lines.append("- none")
    lines.extend(["", "## Missing Metrics Schemas", ""])
    lines.extend(f"- {item}" for item in readiness["missing_metrics_schemas"]) if readiness["missing_metrics_schemas"] else lines.append("- none")
    lines.extend(["", "## Missing User Answers", ""])
    lines.extend(f"- `{item['id']}` {item['question']}" for item in readiness["missing_user_answers"]) if readiness["missing_user_answers"] else lines.append("- none")
    lines.extend(["", "## Latest Lint", "", f"Status: `{readiness.get('last_lint_status', 'not_run')}`"])
    lines.extend(["", "## Latest Contract Tests", ""])
    if readiness["contract_tests"]:
        for item in readiness["contract_tests"]:
            lines.append(f"- `{item['capability_id']}` {item['status']}")
    else:
        lines.append("- none")
    lines.extend(["", "## Next Actionable Blockers", ""])
    lines.extend(f"- {item}" for item in readiness["next_blockers"]) if readiness["next_blockers"] else lines.append("- none")
    write_text(paths.vibe / "adapter_doctor.md", "\n".join(lines) + "\n")
    write_json(paths.vibe / "adapter_readiness.json", readiness)
    record_event(paths, "adapter_doctor_written", "Wrote adapter readiness report", status=readiness["maturity_level"], payload=readiness)
    return readiness


def adapter_readiness(paths: VibePaths) -> dict[str, Any]:
    manifest = load_adapter_manifest(paths)
    lint = lint_adapter(paths) if adapter_path(paths).exists() else read_json(paths.vibe / "adapter_lint.json", {})
    contract_tests = []
    contract_by_cap: dict[str, dict[str, Any]] = {}
    if (paths.vibe / "contract_tests").exists():
        for path in sorted((paths.vibe / "contract_tests").glob("*.json")):
            result = read_json(path, {})
            contract_tests.append(result)
            if result.get("capability_id"):
                contract_by_cap[str(result["capability_id"])] = result
    active = [cap.id for cap in manifest.capabilities if cap.status == "active"]
    active_by_task = {cap.task_type: cap.id for cap in manifest.capabilities if cap.status == "active"}
    active_backends = sorted({backend for cap in manifest.capabilities if cap.status == "active" for backend in cap.resources.allowed_backends})
    draft = [cap.id for cap in manifest.capabilities if cap.status in {"candidate", "draft"}]
    blocked = [cap.id for cap in manifest.capabilities if cap.status.startswith("blocked_")]
    blocked_real = [cap.id for cap in manifest.capabilities if cap.status.startswith("blocked_") and cap.task_type in REAL_EXPERIMENT_TASKS]
    missing_scripts = []
    missing_metrics = []
    draft_missing_metrics = []
    contract_failures = []
    for cap in manifest.capabilities:
        command = cap.entrypoint.get("command", "")
        if command and command.split():
            script = shlex.split(command)[1] if command.startswith("python ") and len(shlex.split(command)) > 1 else ""
            if script and not (paths.root / script).exists():
                missing_scripts.append(f"{cap.id}: {script}")
        if cap.status == "active" and not (cap.metrics_schema.required or cap.metrics_schema.types):
            missing_metrics.append(cap.id)
        elif cap.status == "draft" and not (cap.metrics_schema.required or cap.metrics_schema.types):
            draft_missing_metrics.append(cap.id)
        if cap.status == "active":
            contract = contract_by_cap.get(cap.id, {})
            if contract.get("status") != "passed" or cap.activation.get("contract_status") != "passed":
                contract_failures.append(cap.id)
    missing_answers = [q.model_dump() for q in manifest.open_questions if q.severity == "blocker" and not q.confirmed]
    maturity = derive_maturity(manifest)
    readiness_base = (
        bool(active)
        and lint.get("ok", False)
        and not missing_answers
        and not missing_scripts
        and not missing_metrics
        and not contract_failures
    )
    active_tasks = set(active_by_task)
    ready_for_instrumentation = readiness_base and bool(active_tasks & INSTRUMENTATION_TASKS)
    ready_for_evaluation = readiness_base and bool(active_tasks & EVALUATION_TASKS)
    ready_for_training = readiness_base and bool(active_tasks & TRAINING_TASKS)
    ready_for_long_run = readiness_base and bool(active_tasks & LONG_RUN_TASKS)
    ready_for_real = readiness_base and bool(active_tasks & REAL_EXPERIMENT_TASKS)
    ready_for_slurm_real = ready_for_real and "slurm" in active_backends
    blockers = []
    if not active:
        blockers.append("activate at least one instrumentation capability")
    blockers.extend(f"answer {q['id']}" for q in missing_answers[:5])
    blockers.extend(f"fix script {item}" for item in missing_scripts[:5])
    blockers.extend(f"define metrics schema for active capability {item}" for item in missing_metrics[:5])
    if not active:
        blockers.extend(f"define metrics schema for draft capability {item}" for item in draft_missing_metrics[:3])
    blockers.extend(f"rerun contract test for {item}" for item in contract_failures[:5])
    if ready_for_instrumentation and not ready_for_real:
        blockers.append("complete real-experiment adapter onboarding: activate evaluation, metrics, baseline, training, or long-run capability")
    return {
        "adapter_revision": manifest.adapter_revision,
        "maturity_level": maturity,
        "ready_for_experiments": ready_for_real,
        "ready_for_instrumentation": ready_for_instrumentation,
        "ready_for_evaluation": ready_for_evaluation,
        "ready_for_training": ready_for_training,
        "ready_for_long_run": ready_for_long_run,
        "ready_for_real_experiments": ready_for_real,
        "ready_for_slurm_real_experiments": ready_for_slurm_real,
        "active_capabilities": active,
        "active_capabilities_by_task": active_by_task,
        "active_backends": active_backends,
        "draft_capabilities": draft,
        "blocked_capabilities": blocked,
        "blocked_real_experiment_capabilities": blocked_real,
        "missing_scripts": missing_scripts,
        "missing_metrics_schemas": missing_metrics,
        "draft_missing_metrics_schemas": draft_missing_metrics,
        "missing_user_answers": missing_answers,
        "last_lint_status": "passed" if lint.get("ok") else "failed" if lint else "not_run",
        "lint": lint,
        "contract_tests": contract_tests,
        "contract_failures": contract_failures,
        "next_blockers": blockers,
        "updated_at": utc_now(),
    }


def write_real_experiment_gap_report(paths: VibePaths, readiness: dict[str, Any] | None = None) -> dict[str, Any]:
    readiness = readiness or adapter_readiness(paths)
    manifest = load_adapter_manifest(paths)
    real_caps = [cap for cap in manifest.capabilities if cap.task_type in REAL_EXPERIMENT_TASKS]
    gaps = []
    if not readiness.get("ready_for_real_experiments"):
        gaps.extend(
            [
                "activate at least one real-experiment capability, such as evaluation_smoke, metrics_export, baseline_compare, train_smoke, train_gate, or long_run_submit",
                "define a metrics JSON contract and expected artifact paths for the selected capability",
                "define a baseline or proxy comparison source for result interpretation",
                "define an execution backend policy, including allowed local, Slurm, or project-specific backends",
                "define result collection logic that produces schema-valid metrics",
                "record project-specific safety rules in policy or adapter fields before enabling automatic submission",
            ]
        )
    if not readiness.get("ready_for_slurm_real_experiments"):
        gaps.append("if Slurm execution is required, add slurm to the selected capability resource policy allowed_backends and validate submit/monitor/collect commands")
    report = {
        "created_at": utc_now(),
        "ready_for_instrumentation": readiness.get("ready_for_instrumentation", False),
        "ready_for_real_experiments": readiness.get("ready_for_real_experiments", False),
        "ready_for_slurm_real_experiments": readiness.get("ready_for_slurm_real_experiments", False),
        "active_capabilities_by_task": readiness.get("active_capabilities_by_task", {}),
        "blocked_real_experiment_capabilities": readiness.get("blocked_real_experiment_capabilities", []),
        "real_experiment_capabilities": [
            {"id": cap.id, "task_type": cap.task_type, "status": cap.status, "allowed_backends": cap.resources.allowed_backends}
            for cap in real_caps
        ],
        "gaps": gaps,
    }
    write_json(paths.vibe / "adapter_real_experiment_gaps.json", report)
    write_text(paths.vibe / "adapter_real_experiment_gaps.md", render_real_experiment_gap_report(report))
    return report


def render_real_experiment_gap_report(report: dict[str, Any]) -> str:
    lines = [
        "# Real Experiment Adapter Gaps",
        "",
        "This report is project-generic. It describes which adapter contracts are missing before VibeResearch can count backend-submitted method/evaluation runs as real experiments.",
        "",
        f"Ready for instrumentation: `{report['ready_for_instrumentation']}`",
        f"Ready for real experiments: `{report['ready_for_real_experiments']}`",
        f"Ready for Slurm-backed real experiments: `{report['ready_for_slurm_real_experiments']}`",
        "",
        "## Real Experiment Capabilities",
        "",
    ]
    if report.get("real_experiment_capabilities"):
        for cap in report["real_experiment_capabilities"]:
            lines.append(f"- `{cap['id']}` task=`{cap['task_type']}` status=`{cap['status']}` backends=`{', '.join(cap.get('allowed_backends', [])) or 'none'}`")
    else:
        lines.append("- none")
    lines.extend(["", "## Required Adapter Work", ""])
    if report.get("gaps"):
        lines.extend(f"- {gap}" for gap in report["gaps"])
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def run_contract_test(paths: VibePaths, capability_id: str) -> dict[str, Any]:
    manifest = load_adapter_manifest(paths)
    cap = find_capability(manifest, capability_id)
    if not cap:
        result = {"capability_id": capability_id, "status": "failed", "errors": ["unknown capability"], "created_at": utc_now()}
        write_contract_result(paths, capability_id, result)
        return result
    errors = []
    dryrun_command = cap.dryrun.get("command", "")
    if is_placeholder_command(dryrun_command):
        errors.append("dryrun command is placeholder")
    if not cap.entrypoint.get("command"):
        errors.append("entrypoint.command is missing")
    if not (cap.metrics_schema.required or cap.metrics_schema.types):
        errors.append("metrics schema is missing")
    output_path = cap.outputs.get("expected_output_path") or (cap.artifact_rules.expected_outputs[0] if cap.artifact_rules.expected_outputs else "")
    if not output_path:
        errors.append("expected output is missing")
    if not errors:
        try:
            proc = subprocess.run(shlex.split(dryrun_command), cwd=paths.root, text=True, capture_output=True, timeout=30, check=False)
            if proc.returncode != 0:
                errors.append("dryrun failed: " + (proc.stderr.strip() or proc.stdout.strip())[:300])
        except Exception as exc:
            errors.append(f"dryrun failed: {exc}")
    expected = paths.root / output_path if output_path else None
    if expected and not expected.exists():
        errors.append(f"expected output missing: {output_path}")
    if expected and expected.exists():
        try:
            metrics = json.loads(expected.read_text())
            errors.extend(validate_sample_metrics(metrics, cap.metrics_schema))
        except Exception as exc:
            errors.append(f"sample metrics parse failed: {exc}")
    result = {
        "capability_id": capability_id,
        "status": "passed" if not errors else "failed",
        "errors": errors,
        "created_at": utc_now(),
        "command_template_hash": hash_string(cap.entrypoint.get("command", "")),
        "metrics_schema_hash": hash_dict(cap.metrics_schema.model_dump()),
        "artifact_rule_hash": hash_dict(cap.artifact_rules.model_dump()),
    }
    write_contract_result(paths, capability_id, result)
    append_jsonl(paths.vibe / "adapter_history.jsonl", {"event": "adapter_contract_test", **result})
    record_event(paths, "adapter_contract_test", f"{capability_id}: {result['status']}", status=result["status"], payload=result)
    return result


def validate_sample_metrics(metrics: dict[str, Any], schema: MetricsSchema) -> list[str]:
    errors = []
    for key in schema.required:
        if key not in metrics:
            errors.append(f"missing required metric {key}")
    for key, value_type in schema.types.items():
        if key not in metrics:
            continue
        if value_type == "number" and not isinstance(metrics[key], (int, float)):
            errors.append(f"{key} must be number")
        if value_type == "string" and not isinstance(metrics[key], str):
            errors.append(f"{key} must be string")
        if value_type in {"bool", "boolean"} and not isinstance(metrics[key], bool):
            errors.append(f"{key} must be boolean")
    return errors


def write_contract_result(paths: VibePaths, capability_id: str, result: dict[str, Any]) -> None:
    write_json(paths.vibe / "contract_tests" / f"{capability_id}.json", result)
    lines = ["# Contract Test", "", f"Capability: `{capability_id}`", f"Status: `{result['status']}`", ""]
    if result.get("errors"):
        lines.extend(["## Errors", ""])
        lines.extend(f"- {error}" for error in result["errors"])
    write_text(paths.vibe / "contract_tests" / f"{capability_id}.md", "\n".join(lines) + "\n")


def activate_capability(paths: VibePaths, capability_id: str, *, user_confirmation: str = "") -> dict[str, Any]:
    manifest = load_adapter_manifest(paths)
    cap = find_capability(manifest, capability_id)
    if not cap:
        raise ValueError(f"Unknown capability: {capability_id}")
    result = read_json(paths.vibe / "contract_tests" / f"{capability_id}.json", {})
    if result.get("status") != "passed":
        raise RuntimeError(f"Capability {capability_id} cannot activate without passed contract test")
    blockers = [q.id for q in manifest.open_questions if q.severity == "blocker" and not q.confirmed and (not q.blocks_capability or q.blocks_capability == capability_id)]
    if blockers:
        raise RuntimeError(f"Capability {capability_id} has unanswered blocker questions: {', '.join(blockers)}")
    if cap.task_type in {"train_smoke", "train_gate", "long_run_submit"} and not has_active_task(manifest, {"evaluation_smoke", "metrics_export"}):
        raise RuntimeError("Training capability requires active evaluation or metrics export capability")
    if cap.task_type == "baseline_compare" and not has_active_task(manifest, {"baseline_inventory"}):
        raise RuntimeError("Baseline compare requires active baseline inventory capability")
    cap.status = "active"
    cap.activation = {
        "activated_at": utc_now(),
        "contract_status": "passed",
        "contract_test_result_id": result.get("created_at", ""),
        "command_template_hash": result.get("command_template_hash") or hash_string(cap.entrypoint.get("command", "")),
        "metrics_schema_hash": result.get("metrics_schema_hash") or hash_dict(cap.metrics_schema.model_dump()),
        "artifact_rule_hash": result.get("artifact_rule_hash") or hash_dict(cap.artifact_rules.model_dump()),
        "user_confirmation": user_confirmation,
    }
    write_adapter_manifest(paths, manifest)
    record = {"event": "adapter_capability_activated", "capability_id": capability_id, "capability_version": cap.version, "adapter_revision": manifest.adapter_revision, **cap.activation}
    append_jsonl(paths.vibe / "adapter_history.jsonl", record)
    record_event(paths, "adapter_capability_activated", capability_id, status="active", payload=record)
    clear_adapter_block_if_ready(paths)
    return record


def find_capability(manifest: AdapterManifest, capability_id: str) -> AdapterCapability | None:
    for cap in manifest.capabilities:
        if cap.id == capability_id:
            return cap
    return None


def has_active_task(manifest: AdapterManifest, tasks: set[str]) -> bool:
    return any(cap.status == "active" and cap.task_type in tasks for cap in manifest.capabilities)


def hash_string(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def set_adapter_block(paths: VibePaths, reason: str) -> None:
    state = read_json(paths.state / "state.json", {})
    state["status"] = "blocked_missing_adapter"
    state["blocked_reason"] = reason
    state["next_action"] = "vibe adapter doctor"
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)


def clear_adapter_block_if_ready(paths: VibePaths) -> None:
    readiness = adapter_readiness(paths)
    if not readiness["ready_for_real_experiments"]:
        return
    state = read_json(paths.state / "state.json", {})
    if state.get("status") == "blocked_missing_adapter":
        state["status"] = "initialized"
        state["blocked_reason"] = ""
        state["next_action"] = "vibe plan-cycle"
        state["updated_at"] = utc_now()
        write_json(paths.state / "state.json", state)


def bootstrap_adapter_on_init(paths: VibePaths, *, minimal: bool) -> None:
    adapter_init(paths, minimal=minimal)
    if not minimal:
        adapter_discover(paths)
        adapter_draft(paths)
        bootstrap_script_plan(paths)
        adapter_lint(paths)
        adapter_doctor(paths)
        set_adapter_block(paths, "adapter/script bootstrap is incomplete; run vibe adapter doctor and activate instrumentation first, then complete real-experiment adapter gaps")


def script_bootstrap(paths: VibePaths, *, generate: bool = True, script_dir: str = ".vibe/scripts") -> Path:
    path = bootstrap_script_plan(paths, script_dir=script_dir, generate=generate)
    append_jsonl(paths.vibe / "adapter_history.jsonl", {"event": "script_bootstrap", "created_at": utc_now(), "generate": generate, "script_dir": script_dir})
    record_event(paths, "script_bootstrap", f"Script bootstrap {'generated wrappers' if generate else 'planned wrappers'}", status="draft")
    return path
