from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from vibe_research.cli import app
from vibe_research.io import read_jsonl


runner = CliRunner()


def invoke(*args: str):
    return runner.invoke(app, list(args), catch_exceptions=False, env={}, prog_name="vibe")


def test_init_creates_session_kernel_files(tmp_path: Path):
    result = invoke("init", "--target", str(tmp_path))
    assert result.exit_code == 0

    kernel = tmp_path / ".vibe" / "kernel"
    expected = {
        "PROJECT_KERNEL.md",
        "PROBLEM_STATE.md",
        "FAILURE_SIGNATURES.md",
        "OPEN_DEBTS.md",
        "NEGATIVE_MEMORY.md",
        "SESSION_PROTOCOL.md",
        "EVIDENCE_LEDGER.jsonl",
    }
    assert expected <= {path.name for path in kernel.iterdir()}

    status = invoke("kernel", "status", "--target", str(tmp_path))
    assert status.exit_code == 0
    assert "Status: ok" in status.output


def test_kernel_check_blocks_missing_core_files(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    (tmp_path / ".vibe" / "kernel" / "PROBLEM_STATE.md").unlink()

    check = invoke("kernel", "check-protocol", "--target", str(tmp_path))
    assert check.exit_code == 1
    assert "PROBLEM_STATE.md" in check.output


def test_kernel_evidence_ledger_is_append_only_and_traceable(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0

    first = invoke(
        "kernel",
        "record-evidence",
        "--target",
        str(tmp_path),
        "--session-role",
        "reflector",
        "--source",
        "unit-test",
        "--artifact",
        ".vibe/runs/r001/result.md",
        "--evidence-type",
        "metric",
        "--belief-update",
        "subset metric improved",
        "--next-action",
        "promote to fold0 debt",
        "--session-id",
        "s-reflect",
        "--target-id",
        "r001",
        "--action",
        "reflect",
    )
    assert first.exit_code == 0
    second = invoke(
        "kernel",
        "record-evidence",
        "--target",
        str(tmp_path),
        "--session-role",
        "archivist",
        "--source",
        "unit-test",
        "--artifact",
        ".vibe/kernel/NEGATIVE_MEMORY.md",
        "--evidence-type",
        "negative",
        "--belief-update",
        "route should not repeat",
        "--next-action",
        "block duplicate plan",
        "--session-id",
        "s-archive",
        "--target-id",
        "r001",
        "--action",
        "archive",
    )
    assert second.exit_code == 0

    records = read_jsonl(tmp_path / ".vibe" / "kernel" / "EVIDENCE_LEDGER.jsonl")
    assert [record["artifact"] for record in records] == [
        ".vibe/runs/r001/result.md",
        ".vibe/kernel/NEGATIVE_MEMORY.md",
    ]


def test_kernel_blocks_single_session_closed_loop_claim(tmp_path: Path):
    assert invoke("init", "--target", str(tmp_path)).exit_code == 0
    claims = [
        ("planner", "plan"),
        ("reviewer", "review"),
        ("executor", "execute"),
    ]
    for role, action in claims:
        result = invoke(
            "kernel",
            "record-evidence",
            "--target",
            str(tmp_path),
            "--session-role",
            role,
            "--source",
            "unit-test",
            "--artifact",
            f".vibe/{action}.md",
            "--evidence-type",
            "feasibility",
            "--belief-update",
            f"{action} claim",
            "--next-action",
            "continue",
            "--session-id",
            "s-one",
            "--target-id",
            "cycle001",
            "--action",
            action,
        )
        assert result.exit_code == 0

    check = invoke(
        "kernel",
        "check-protocol",
        "--target",
        str(tmp_path),
        "--session-id",
        "s-one",
        "--target-id",
        "cycle001",
        "--action",
        "reflect",
    )
    assert check.exit_code == 1
    assert "closed-loop duties" in check.output
