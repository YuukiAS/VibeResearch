"""Generic real-experiment readiness and progress accounting."""

from __future__ import annotations

from typing import Any

from .config import load_config
from .io import append_jsonl, read_json, utc_now, write_json, write_text
from .paths import VibePaths


INSTRUMENTATION_TASKS = {"environment_probe", "data_probe", "baseline_inventory"}
EVALUATION_TASKS = {"evaluation_smoke", "metrics_export", "baseline_compare"}
TRAINING_TASKS = {"train_smoke", "train_gate"}
LONG_RUN_TASKS = {"long_run_submit"}
REAL_EXPERIMENT_TASKS = EVALUATION_TASKS | TRAINING_TASKS | LONG_RUN_TASKS


def task_group(task_type: str) -> str:
    if task_type in INSTRUMENTATION_TASKS:
        return "instrumentation"
    if task_type in EVALUATION_TASKS:
        return "evaluation"
    if task_type in TRAINING_TASKS:
        return "training"
    if task_type in LONG_RUN_TASKS:
        return "long_run"
    return "unknown"


def run_kind_from_task(task_type: str) -> str:
    group = task_group(task_type)
    if group == "instrumentation":
        return "instrumentation"
    if group in {"evaluation", "training", "long_run"}:
        return "real_experiment"
    return "unknown"


def summarize_real_experiment_progress(paths: VibePaths, *, write: bool = False) -> dict[str, Any]:
    state = read_json(paths.state / "state.json", {})
    config = load_config(paths)
    target_count = int(config.get("research", {}).get("real_experiment_target_count", 3) or 3)
    rows = []
    countable = []
    non_counting = []
    for run_id, run in sorted(state.get("runs", {}).items()):
        row = classify_run(paths, run_id, run)
        rows.append(row)
        if row["counts_toward_real_experiment_cycle"]:
            countable.append(row)
        elif (
            row["run_kind"] == "real_experiment"
            and row["status"] in {"failed", "timeout", "cancelled", "dryrun_failed", "collected"}
            and row.get("requires_repair", True)
        ):
            non_counting.append(row)
    progress = {
        "created_at": utc_now(),
        "target_count": target_count,
        "observed_count": len(countable),
        "complete": len(countable) >= target_count,
        "countable_runs": countable,
        "non_counting_real_experiment_runs": non_counting,
        "all_runs": rows,
        "next_action": next_real_experiment_action(target_count, countable, non_counting, rows),
    }
    if write:
        write_json(paths.research / "real_experiment_progress.json", progress)
        write_text(paths.research / "real_experiment_progress.md", render_real_experiment_progress(progress))
    return progress


def classify_run(paths: VibePaths, run_id: str, run: dict[str, Any]) -> dict[str, Any]:
    adapter_meta = run.get("adapter_metadata", {}) if isinstance(run.get("adapter_metadata"), dict) else {}
    evaluation = run.get("evaluation", {}) if isinstance(run.get("evaluation"), dict) else {}
    task_type = str(adapter_meta.get("task_type", ""))
    run_kind = str(run.get("run_kind") or run_kind_from_task(task_type))
    metrics = read_json(paths.runs / run_id / "metrics.json", {})
    status = str(run.get("status", ""))
    superseded_by = str(run.get("superseded_by") or run.get("replacement_run_id") or run.get("replaced_by") or "")
    has_metrics = bool(metrics and not metrics.get("missing_metrics"))
    schema_valid = metrics.get("schema_status") == "valid"
    interpretable = bool(has_metrics and schema_valid)
    has_baseline = has_baseline_comparison(evaluation, metrics, run)
    submitted = bool(run.get("backend") or read_json(paths.runs / run_id / "launch.json", {}))
    reason = ""
    counts = False
    requires_repair = False
    if run_kind != "real_experiment":
        reason = "not_real_experiment_run"
    elif superseded_by and status in {"failed", "timeout", "cancelled", "dryrun_failed"}:
        reason = f"non_counting_superseded_by:{superseded_by}"
    elif status in {"failed", "timeout", "cancelled", "dryrun_failed"}:
        reason = f"non_counting_execution_failure:{status}"
        requires_repair = True
    elif not submitted:
        reason = "non_counting_no_backend_submission"
        requires_repair = True
    elif not interpretable:
        reason = "non_counting_metrics_not_interpretable"
        requires_repair = status in {"collected", "finished"}
    elif not has_baseline:
        reason = "non_counting_missing_baseline_comparison"
        requires_repair = status in {"collected", "finished"}
    else:
        counts = True
        reason = "counted"
    return {
        "run_id": run_id,
        "cycle_id": run.get("cycle_id", ""),
        "direction_id": run.get("direction_id", ""),
        "status": status,
        "run_kind": run_kind,
        "task_type": task_type,
        "capability_id": adapter_meta.get("capability_id", ""),
        "backend": run.get("backend", ""),
        "has_backend_submission": submitted,
        "has_interpretable_metrics": interpretable,
        "has_baseline_comparison": has_baseline,
        "counts_toward_real_experiment_cycle": counts,
        "classification": reason,
        "superseded_by": superseded_by,
        "requires_repair": requires_repair,
    }


def has_baseline_comparison(evaluation: dict[str, Any], metrics: dict[str, Any], run: dict[str, Any]) -> bool:
    nested_metrics = metrics.get("metrics", {}) if isinstance(metrics.get("metrics"), dict) else {}
    return bool(
        evaluation.get("baseline_comparison_target")
        or metrics.get("baseline_comparison_target")
        or metrics.get("baseline_metrics")
        or metrics.get("metric_delta")
        or nested_metrics.get("baseline_metrics")
        or nested_metrics.get("metric_delta")
        or run.get("baseline_comparison_target")
    )


def record_repair_issue(paths: VibePaths, run_id: str, run: dict[str, Any], classification: str, details: dict[str, Any] | None = None) -> None:
    row = {
        "created_at": utc_now(),
        "run_id": run_id,
        "cycle_id": run.get("cycle_id", ""),
        "status": run.get("status", ""),
        "classification": classification,
        "details": details or {},
        "next_action": "repair execution, metric collection, baseline comparison, or adapter contract before counting this as a real experiment",
    }
    append_jsonl(paths.research / "repair_queue.jsonl", row)


def next_real_experiment_action(target_count: int, countable: list[dict[str, Any]], non_counting: list[dict[str, Any]], all_runs: list[dict[str, Any]] | None = None) -> str:
    if len(countable) >= target_count:
        return "real experiment target count reached; reflect and decide whether to continue"
    active_replacements = [
        row
        for row in (all_runs or [])
        if row.get("run_kind") == "real_experiment" and row.get("status") in {"queued", "submitted", "pending", "running", "dry_submitted", "submitted_dry"}
    ]
    if active_replacements:
        return "monitor active replacement real experiments; collect trusted metrics when they finish"
    if non_counting:
        return "repair or classify non-counting real experiment failures before counting progress"
    return "compile and run adapter-backed real experiments with baseline comparison"


def render_real_experiment_progress(progress: dict[str, Any]) -> str:
    lines = [
        "# Real Experiment Progress",
        "",
        f"Observed count: `{progress['observed_count']}` / `{progress['target_count']}`",
        f"Complete: `{progress['complete']}`",
        f"Next action: {progress['next_action']}",
        "",
        "## Countable Runs",
        "",
    ]
    if progress.get("countable_runs"):
        for row in progress["countable_runs"]:
            lines.append(f"- `{row['run_id']}` {row['classification']} backend={row['backend']} capability={row['capability_id']}")
    else:
        lines.append("- none")
    lines.extend(["", "## Non-Counting Real Experiment Runs", ""])
    if progress.get("non_counting_real_experiment_runs"):
        for row in progress["non_counting_real_experiment_runs"]:
            lines.append(f"- `{row['run_id']}` {row['classification']}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"
