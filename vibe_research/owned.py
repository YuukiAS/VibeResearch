"""Owned framework alpha scaffold, contracts, shadow plans, and audits."""

from __future__ import annotations

import py_compile
import re
from pathlib import Path
from typing import Any

from .io import ensure_dir, read_jsonl, utc_now, write_json, write_text
from .paths import VibePaths


OWNED_REQUIRED_STATUSES = {"approved", "reviewed"}


def owned_dir(paths: VibePaths):
    return ensure_dir(paths.research / "owned")


def load_framework_proposal(paths: VibePaths, proposal_id: str) -> dict[str, Any]:
    proposals = read_jsonl(paths.research / "lineage" / "framework_proposals.jsonl")
    proposal = next((row for row in proposals if row.get("proposal_id") == proposal_id), None)
    if not proposal:
        raise ValueError(f"Unknown framework proposal: {proposal_id}")
    return proposal


def scaffold_owned_framework(paths: VibePaths, proposal_id: str, *, framework_name: str = "", allow_overwrite: bool = False) -> dict[str, Any]:
    proposal = load_framework_proposal(paths, proposal_id)
    blockers: list[str] = []
    if proposal.get("status") not in OWNED_REQUIRED_STATUSES:
        blockers.append("framework_proposal_not_approved")
    name = framework_name or infer_framework_name(proposal.get("downstream_src_target", ""))
    if not name:
        blockers.append("missing_framework_name")
        name = "owned_framework"
    files = scaffold_file_map(paths.root, name, proposal)
    denied = denied_by_agents(paths.root, files.keys())
    blockers.extend(denied)
    existing = [str(path.relative_to(paths.root)) for path in files if path.exists()]
    if existing and not allow_overwrite:
        blockers.extend(f"would_overwrite:{item}" for item in existing)
    if blockers:
        result = {"created_at": utc_now(), "status": "blocked", "proposal_id": proposal_id, "framework_name": name, "blockers": blockers, "files": [str(path) for path in files]}
        write_json(owned_dir(paths) / proposal_id / "scaffold_blocked.json", result)
        return result
    for path, content in files.items():
        write_text(path, content)
    capability = {
        "capability_id": f"{name}-owned-eval-smoke",
        "source": "owned_framework_scaffold",
        "status": "draft",
        "entrypoint": f"python -m {name}.evaluate",
        "contracts": ["import", "config_parse", "dryrun", "metrics_export", "artifact_output", "baseline_comparison"],
        "proposal_id": proposal_id,
        "external_baseline_asset_id": proposal.get("external_baseline_asset_id", ""),
    }
    write_json(paths.vibe / "adapter" / "internal_capabilities" / f"{name}-owned-eval-smoke.json", capability)
    result = {"created_at": utc_now(), "status": "created", "proposal_id": proposal_id, "framework_name": name, "files": [str(path.relative_to(paths.root)) for path in files], "capability": capability}
    write_json(owned_dir(paths) / proposal_id / "scaffold.json", result)
    return result


def owned_contract(paths: VibePaths, framework_name: str) -> dict[str, Any]:
    src = paths.root / "src" / framework_name
    checks = {
        "import_test": (src / "__init__.py").exists(),
        "config_parse_test": (src / "config.py").exists(),
        "dryrun_test": (src / "evaluate.py").exists(),
        "metrics_export_test": file_contains(src / "metrics.py", "export_metrics"),
        "artifact_output_test": file_contains(src / "evaluate.py", "write_artifact"),
        "baseline_comparison_hook": file_contains(src / "evaluate.py", "compare_to_baseline"),
    }
    compile_errors = []
    for path in [src / "__init__.py", src / "config.py", src / "metrics.py", src / "evaluate.py"]:
        if path.exists():
            try:
                py_compile.compile(str(path), doraise=True)
            except py_compile.PyCompileError as exc:
                compile_errors.append(f"{path.relative_to(paths.root)}:{exc.msg}")
    checks["python_compile"] = not compile_errors
    result = {"created_at": utc_now(), "framework_name": framework_name, "passed": all(checks.values()), "checks": checks, "compile_errors": compile_errors}
    write_json(owned_dir(paths) / framework_name / "contract.json", result)
    return result


def owned_shadow_plan(paths: VibePaths, proposal_id: str, *, sample_scope: str = "small_sample") -> dict[str, Any]:
    proposal = load_framework_proposal(paths, proposal_id)
    result = {
        "created_at": utc_now(),
        "proposal_id": proposal_id,
        "mode": "shadow",
        "sample_scope": sample_scope,
        "downstream_src_target": proposal.get("downstream_src_target", ""),
        "external_baseline_asset_id": proposal.get("external_baseline_asset_id", ""),
        "must_not_replace_primary_path": True,
        "comparison_required": True,
    }
    write_json(owned_dir(paths) / proposal_id / "shadow_plan.json", result)
    return result


def owned_design_audit(paths: VibePaths, framework_name: str, *, proposal_id: str = "") -> dict[str, Any]:
    src = paths.root / "src" / framework_name
    files = list(src.rglob("*.py")) if src.exists() else []
    hidden_external_calls = []
    undeclared_dependency_markers = []
    for path in files:
        text = path.read_text(errors="ignore")
        if re.search(r"external_core_call|external_repo|subprocess\.(run|Popen)|git clone", text):
            hidden_external_calls.append(str(path.relative_to(paths.root)))
        if re.search(r"import (torch|tensorflow|sklearn)", text) and "declared_dependency" not in text:
            undeclared_dependency_markers.append(str(path.relative_to(paths.root)))
    contract = owned_contract(paths, framework_name)
    result = {
        "created_at": utc_now(),
        "proposal_id": proposal_id,
        "framework_name": framework_name,
        "owned_core_allowed": not hidden_external_calls and contract.get("passed"),
        "classification": "wrapped_external" if hidden_external_calls else "owned_alpha_candidate",
        "hidden_external_calls": hidden_external_calls,
        "undeclared_dependency_markers": undeclared_dependency_markers,
        "contract": contract,
    }
    write_json(owned_dir(paths) / framework_name / "design_audit.json", result)
    return result


def scaffold_file_map(root: Path, name: str, proposal: dict[str, Any]) -> dict[Path, str]:
    module = root / "src" / name
    return {
        module / "__init__.py": f'"""Owned framework alpha generated from {proposal.get("proposal_id")}."""\n\n__all__ = [\"export_metrics\", \"run_shadow\"]\n',
        module / "config.py": "from __future__ import annotations\n\n\ndef parse_config(config: dict | None = None) -> dict:\n    return dict(config or {})\n",
        module / "metrics.py": "from __future__ import annotations\n\n\ndef export_metrics(values: dict | None = None) -> dict:\n    data = dict(values or {})\n    data.setdefault(\"primary\", 0.0)\n    return data\n",
        module / "evaluate.py": "from __future__ import annotations\n\nimport json\nfrom pathlib import Path\n\nfrom .config import parse_config\nfrom .metrics import export_metrics\n\n\ndef compare_to_baseline(metrics: dict, baseline: dict | None = None) -> dict:\n    return {\"metrics\": metrics, \"baseline\": dict(baseline or {}), \"comparable\": True}\n\n\ndef write_artifact(path: str | Path, payload: dict) -> None:\n    target = Path(path)\n    target.parent.mkdir(parents=True, exist_ok=True)\n    target.write_text(json.dumps(payload, sort_keys=True) + \"\\n\")\n\n\ndef run_shadow(config: dict | None = None) -> dict:\n    parsed = parse_config(config)\n    metrics = export_metrics(parsed.get(\"metrics\", {}))\n    return compare_to_baseline(metrics, parsed.get(\"baseline\", {}))\n\n\nif __name__ == \"__main__\":\n    write_artifact(\".vibe/owned_shadow_metrics.json\", run_shadow({}))\n",
        root / "tests" / f"test_{name}_contract.py": f"from {name}.evaluate import run_shadow\n\n\ndef test_{name}_shadow_contract():\n    result = run_shadow({{}})\n    assert result[\"comparable\"] is True\n    assert \"primary\" in result[\"metrics\"]\n",
        root / "docs" / f"{name}_owned_alpha.md": f"# {name} Owned Alpha\n\nGenerated from `{proposal.get('proposal_id')}`.\n\nExternal baseline: `{proposal.get('external_baseline_asset_id', '')}`.\n",
        root / "config" / f"{name}.yaml": "mode: shadow\n",
    }


def denied_by_agents(root: Path, paths: Any) -> list[str]:
    agents = root / "AGENTS.md"
    if not agents.exists():
        return []
    text = agents.read_text(errors="ignore")
    denied = []
    denied_paths = []
    for line in text.splitlines():
        lower = line.lower()
        if "do not edit" in lower or "forbid:" in lower or "forbidden:" in lower:
            denied_paths.extend(re.findall(r"(src/[A-Za-z0-9_./-]+|tests/[A-Za-z0-9_./-]+|docs/[A-Za-z0-9_./-]+|config/[A-Za-z0-9_./-]+)", line))
    for path in paths:
        rel = str(path.relative_to(root))
        if any(rel.startswith(item.rstrip("/") + "/") or rel == item.rstrip("/") for item in denied_paths):
            denied.append(f"agents_denies:{rel}")
    return denied


def infer_framework_name(target: str) -> str:
    parts = [part for part in Path(target).parts if part not in {"src", "."}]
    return parts[0] if parts else ""


def file_contains(path: Path, needle: str) -> bool:
    return path.exists() and needle in path.read_text(errors="ignore")
