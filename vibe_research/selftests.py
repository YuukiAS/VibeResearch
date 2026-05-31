"""Operator-visible synthetic self-tests for VibeResearch contracts."""

from __future__ import annotations

from typing import Any

from .adapter_schema import AdapterCapability, AdapterManifest, ArtifactRules, MetricsSchema, ResourcePolicy, write_adapter_manifest
from .io import append_jsonl, ensure_dir, read_json, utc_now, write_json, write_text, write_yaml
from .paths import VibePaths
from .project import init_project
from .research_manager import create_experiment, create_hypothesis, default_candidates, sustained_round_audit


def sustained_round_selftest(paths: VibePaths) -> dict[str, Any]:
    """Run an isolated synthetic check of the sustained-round contract."""

    created_at = utc_now()
    run_id = created_at.replace(":", "").replace("-", "").replace("Z", "Z")
    base = paths.vibe / "selftests" / "sustained_round"
    workspace = base / run_id / "workspace"
    init_project(
        workspace,
        force=True,
        root_portal="none",
        goal="Synthetic sustained-round self-test.",
        background="Isolated workspace used to verify VibeResearch sustained-round accounting and provenance.",
    )
    test_paths = VibePaths(workspace)
    install_selftest_adapter(test_paths)
    seed_selftest_research(test_paths)
    seed_selftest_external_provenance(test_paths)
    seed_selftest_completed_rounds(test_paths)
    candidates = default_candidates(test_paths)
    audit = sustained_round_audit(test_paths, target_rounds=3, min_routes_per_round=3)
    errors: list[str] = []
    if len(candidates) < 3:
        errors.append(f"default_candidates_below_three:{len(candidates)}")
    if int(audit.get("completed_round_count", 0) or 0) < 3:
        errors.append(f"completed_round_count_below_three:{audit.get('completed_round_count')}")
    if audit.get("issues"):
        errors.append("audit_issues:" + ",".join(str(item) for item in audit.get("issues", [])))
    status = "passed" if not errors else "failed"
    record = {
        "selftest_id": run_id,
        "created_at": created_at,
        "status": status,
        "target": str(paths.root),
        "workspace": str(test_paths.root),
        "candidate_count": len(candidates),
        "completed_round_count": audit.get("completed_round_count", 0),
        "issues": audit.get("issues", []),
        "errors": errors,
        "audit_path": str(test_paths.research / "sustained_round_audit.json"),
    }
    write_json(base / run_id / "result.json", record)
    write_text(base / run_id / "result.md", render_sustained_round_selftest(record))
    write_json(base / "latest.json", record)
    write_text(base / "latest.md", render_sustained_round_selftest(record))
    return record


def install_selftest_adapter(paths: VibePaths) -> None:
    manifest = AdapterManifest(
        project_id=paths.root.name,
        project_name=paths.root.name,
        capabilities=[
            AdapterCapability(
                id="selftest-metrics-export",
                version="selftest",
                status="active",
                task_type="metrics_export",
                supported_decisions=["collect_more_metrics"],
                description="Synthetic metrics export capability for sustained-round self-tests.",
                dryrun={"command": "python3 -c 'print(\"selftest dryrun\")'"},
                entrypoint={"type": "local", "command": "python3 -c 'print(\"selftest run\")'"},
                outputs={"expected_output_path": ".vibe/selftest_metrics.json", "metrics_file_path": ".vibe/selftest_metrics.json"},
                metrics_schema=MetricsSchema(required=["primary"], types={"primary": "number"}, primary_metric="primary", version="selftest"),
                artifact_rules=ArtifactRules(expected_outputs=[".vibe/selftest_metrics.json"], trusted_path_patterns=[".vibe/*.json"], version="selftest"),
                resources=ResourcePolicy(automatic_submission_allowed=False, user_confirmation_required=False, allowed_backends=["local"]),
                trust_checks=["schema_valid_metrics", "expected_output_exists"],
                contract_tests=["selftest-metrics-export"],
                activation={"contract_status": "passed", "contract_test_result_id": "selftest", "command_template_hash": "selftest", "metrics_schema_hash": "selftest", "artifact_rule_hash": "selftest"},
            )
        ],
        open_questions=[],
    )
    write_adapter_manifest(paths, manifest)
    write_json(paths.vibe / "contract_tests" / "selftest-metrics-export.json", {"capability_id": "selftest-metrics-export", "status": "passed", "created_at": utc_now()})


def seed_selftest_research(paths: VibePaths) -> None:
    for index in range(1, 4):
        hypothesis = create_hypothesis(
            paths,
            f"Self-test route {index}",
            rationale="Synthetic active route for sustained-round self-test.",
            stage="smoke",
            target_metrics=["primary"],
            origin="selftest",
        )
        create_experiment(
            paths,
            hypothesis["hypothesis_id"],
            f"Self-test experiment {index}",
            stage="smoke",
            capability_id="selftest-metrics-export",
            expected_evidence={"kind": "schema_valid_metrics"},
        )


def seed_selftest_external_provenance(paths: VibePaths) -> None:
    append_jsonl(paths.research / "sources.jsonl", {"source_id": "selftest-source", "kind": "paper", "title": "Synthetic sustained-round source", "status": "recorded", "created_at": utc_now()})
    append_jsonl(paths.research / "external_repos.jsonl", {"name": "selftest-repo", "url": "https://example.invalid/selftest.git", "status": "cloned", "created_at": utc_now()})
    append_jsonl(paths.research / "external_repo_analyses.jsonl", {"name": "selftest-repo", "status": "analyzed", "findings": ["synthetic provenance present"], "created_at": utc_now()})


def seed_selftest_completed_rounds(paths: VibePaths) -> None:
    state = read_json(paths.state / "state.json", {})
    state.setdefault("cycles", {})
    state.setdefault("runs", {})
    for cycle_index in range(1, 4):
        cycle_id = f"c{cycle_index:03d}"
        cycle_dir = paths.cycles / cycle_id
        ensure_dir(cycle_dir)
        write_text(cycle_dir / "cycle_reflect.md", "# Reflection\n\n## Run comparison\n\nSynthetic comparison.\n\n## Route classification\n\nAll routes counted.\n")
        write_text(cycle_dir / "cycle_revised_plan.md", "# Revised Plan\n\n## Next-cycle diversity requirement\n\nKeep three distinct routes.\n")
        state["cycles"][cycle_id] = {"cycle_id": cycle_id, "status": "revised", "review_verdict": "APPROVE_WITH_RESOURCE_GUARDS"}
        for route_index in range(1, 4):
            run_id = f"{cycle_id}_r{route_index:03d}"
            state["runs"][run_id] = {
                "run_id": run_id,
                "cycle_id": cycle_id,
                "direction_id": f"route_{route_index:03d}",
                "status": "collected",
                "hypothesis": f"Synthetic completed route {route_index}",
                "adapter_metadata": {"capability_id": "selftest-metrics-export"},
            }
    state["updated_at"] = utc_now()
    write_json(paths.state / "state.json", state)
    write_yaml(paths.vibe / "config.local.yaml", {"local": {"notes": "self-test isolated workspace"}})


def render_sustained_round_selftest(record: dict[str, Any]) -> str:
    lines = [
        "# Sustained Round Self-Test",
        "",
        f"Status: `{record.get('status')}`",
        f"Workspace: `{record.get('workspace')}`",
        f"Candidate count: `{record.get('candidate_count')}`",
        f"Completed round count: `{record.get('completed_round_count')}`",
        "",
        "## Issues",
    ]
    lines.extend([f"- `{issue}`" for issue in record.get("issues", [])] or ["- none"])
    lines.extend(["", "## Errors"])
    lines.extend([f"- `{error}`" for error in record.get("errors", [])] or ["- none"])
    return "\n".join(lines) + "\n"
