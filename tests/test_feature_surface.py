from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def test_v0108_generic_research_feature_surfaces_import_and_cli_help(tmp_path: Path):
    result = invoke("init", "--target", str(tmp_path), "--goal", "generic goal", "--background", "generic background", "--no-root-portal")
    assert result.exit_code == 0

    for command in ["lineage", "internalization", "scout", "portfolio", "owned", "optimize"]:
        help_result = invoke(command, "--help")
        assert help_result.exit_code == 0

    asset = invoke(
        "lineage",
        "add-external-asset",
        "--target",
        str(tmp_path),
        "--asset-type",
        "repo",
        "--title",
        "generic_baseline",
        "--source",
        "https://example.org/baseline",
        "--dependency-mode",
        "regression_baseline",
    )
    assert asset.exit_code == 0
    asset_id = json.loads(asset.output)["asset_id"]

    finding = invoke(
        "scout",
        "add-finding",
        "--target",
        str(tmp_path),
        "--title",
        "baseline reference",
        "--url-or-ref",
        "https://example.org/paper",
        "--summary",
        "task specific baseline reference with implementation details",
        "--task-match",
        "0.9",
        "--method-match",
        "0.9",
        "--dataset-match",
        "0.8",
        "--metric-match",
        "0.8",
        "--failure-mode-match",
        "0.8",
        "--actionability",
        "0.8",
        "--credibility",
        "0.8",
    )
    assert finding.exit_code == 0
    finding_id = json.loads(finding.output)["finding_id"]
    triage = invoke("scout", "triage", finding_id, "--target", str(tmp_path))
    assert triage.exit_code == 0
    assert json.loads(triage.output)["allowed_for_internalization"] is True

    proposal = invoke(
        "internalization",
        "propose",
        "--target",
        str(tmp_path),
        "--title",
        "generic owned candidate",
        "--external-baseline-asset-id",
        asset_id,
        "--hypothesis-id",
        "hyp_001",
        "--asset-id",
        asset_id,
        "--design-summary",
        "generic owned design",
        "--module-design",
        "src/generic_owned",
        "--data-flow",
        "input to metrics",
        "--metrics-schema-ref",
        "primary",
        "--rollback-strategy",
        "return to external baseline",
        "--minimal-scope",
        "shadow eval",
        "--downstream-src-target",
        "src/generic_owned",
        "--remaining-upside",
        "clear route",
        "--status",
        "approved",
        "--scout-evidence-id",
        finding_id,
    )
    assert proposal.exit_code == 0
    proposal_id = json.loads(proposal.output)["proposal_id"]

    assert invoke("portfolio", "track-memo", "--target", str(tmp_path)).exit_code == 0
    scaffold = invoke("owned", "scaffold", proposal_id, "--framework-name", "generic_owned", "--target", str(tmp_path))
    assert scaffold.exit_code == 0
    assert invoke("owned", "contract", "generic_owned", "--target", str(tmp_path)).exit_code == 0
    assert invoke("optimize", "memory", "--target", str(tmp_path), "--ablation-key", "generic", "--outcome", "failed").exit_code == 0
