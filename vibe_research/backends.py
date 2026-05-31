"""Execution backends for local and Slurm jobs."""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_config
from .io import ensure_dir, utc_now, write_text
from .manifest import load_manifest
from .paths import VibePaths
from .slurm import choose_partition, classify_failure, render_sbatch, slurm_gres_for_partition


@dataclass
class PollResult:
    status: str
    finished: bool
    details: dict[str, Any]


class ExecutionBackend:
    name = "base"

    def __init__(self, paths: VibePaths, config: dict[str, Any]):
        self.paths = paths
        self.config = config

    def submit(self, run_id: str, *, dry: bool = False) -> dict[str, Any]:
        raise NotImplementedError

    def poll(self, launch: dict[str, Any]) -> PollResult:
        raise NotImplementedError

    def cancel(self, launch: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class LocalBackend(ExecutionBackend):
    name = "local"

    def submit(self, run_id: str, *, dry: bool = False) -> dict[str, Any]:
        manifest = load_manifest(self.paths, run_id).model_dump()
        command = manifest["entrypoint"]["command"]
        log_path = self.paths.runs / run_id / "artifacts" / "run.log"
        ensure_dir(log_path.parent)
        launcher = self._choose_launcher()
        launch = {
            "run_id": run_id,
            "cycle_id": manifest.get("cycle_id", ""),
            "backend": "local",
            "launch_workdir": str(self.paths.root.resolve()),
            "launcher": launcher,
            "command": command,
            "submitted_at": utc_now(),
            "status": "dry_submitted" if dry else "submitted",
            "job_id": f"local-{run_id}" if dry else "",
            "log_path": str(log_path),
            "resource_request": manifest.get("resources", {}),
        }
        if dry:
            return launch
        if launcher == "tmux":
            session = self._tmux_session(run_id)
            done_path = self.paths.runs / run_id / "artifacts" / "exitcode.txt"
            shell_command = f"cd {shlex.quote(str(self.paths.root))} && ({command}) > {shlex.quote(str(log_path))} 2>&1; echo $? > {shlex.quote(str(done_path))}"
            result = subprocess.run(["tmux", "new-session", "-d", "-s", session, shell_command], text=True, capture_output=True, check=False)
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip() or result.stdout.strip())
            launch.update({"job_id": f"tmux-{session}", "tmux_session": session, "exitcode_path": str(done_path)})
        else:
            with log_path.open("w") as handle:
                proc = subprocess.Popen(shlex.split(command), cwd=self.paths.root, stdout=handle, stderr=subprocess.STDOUT)
            launch.update({"job_id": f"pid-{proc.pid}", "pid": proc.pid})
        return launch

    def poll(self, launch: dict[str, Any]) -> PollResult:
        if launch.get("status") == "dry_submitted":
            return PollResult("finished", True, {"dry": True})
        if launch.get("launcher") == "tmux":
            session = launch.get("tmux_session")
            result = subprocess.run(["tmux", "has-session", "-t", str(session)], text=True, capture_output=True, check=False)
            if result.returncode == 0:
                return PollResult("running", False, {"tmux_session": session})
            exitcode = read_optional_text(Path(launch.get("exitcode_path", ""))).strip()
            return PollResult("finished", True, {"tmux_session": session, "exitcode": exitcode or "unknown"})
        pid = launch.get("pid")
        if not pid:
            return PollResult("finished", True, {"reason": "no pid"})
        try:
            os.kill(int(pid), 0)
            return PollResult("running", False, {"pid": pid})
        except OSError:
            return PollResult("finished", True, {"pid": pid})

    def cancel(self, launch: dict[str, Any]) -> dict[str, Any]:
        if launch.get("launcher") == "tmux" and launch.get("tmux_session"):
            result = subprocess.run(["tmux", "kill-session", "-t", launch["tmux_session"]], text=True, capture_output=True, check=False)
            return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
        if launch.get("pid"):
            try:
                os.kill(int(launch["pid"]), signal.SIGTERM)
                return {"returncode": 0, "signal": "SIGTERM"}
            except OSError as exc:
                return {"returncode": 1, "error": str(exc)}
        return {"returncode": 0, "status": "nothing_to_cancel"}

    def _choose_launcher(self) -> str:
        local = self.config.get("execution", {}).get("local", {})
        requested = local.get("launcher", "auto")
        if requested == "auto":
            return "tmux" if shutil.which("tmux") else "popen"
        if requested == "tmux" and not shutil.which("tmux"):
            return "popen"
        return requested

    def _tmux_session(self, run_id: str) -> str:
        prefix = self.config.get("execution", {}).get("local", {}).get("tmux_session_prefix", "vibe")
        return f"{prefix}-{self.paths.root.name}-{run_id}".replace("_", "-")[:80]


class SlurmBackend(ExecutionBackend):
    name = "slurm"

    def submit(self, run_id: str, *, dry: bool = False) -> dict[str, Any]:
        manifest = load_manifest(self.paths, run_id).model_dump()
        artifacts = self.paths.runs / run_id / "artifacts"
        ensure_dir(artifacts)
        partition, partition_reason = choose_partition(manifest, self.config)
        script_path = artifacts / f"{run_id}.sbatch"
        out_path = artifacts / "slurm-%j.out"
        err_path = artifacts / "slurm-%j.err"
        script = render_sbatch(manifest, workdir=self.paths.root, output=out_path, error=err_path, partition=partition, config=self.config)
        write_text(script_path, script)
        launch = {
            "run_id": run_id,
            "cycle_id": manifest.get("cycle_id", ""),
            "backend": "slurm",
            "launch_workdir": str(self.paths.root.resolve()),
            "command": manifest["entrypoint"]["command"],
            "submitted_at": utc_now(),
            "status": "dry_submitted" if dry else "submitted",
            "job_id": f"slurm-dry-{run_id}" if dry else "",
            "partition": partition,
            "partition_reason": partition_reason,
            "sbatch_path": str(script_path),
            "log_path": str(out_path),
            "error_path": str(err_path),
            "resource_request": manifest.get("resources", {}),
        }
        if dry:
            return launch
        result = subprocess.run(["sbatch", str(script_path)], cwd=self.paths.root, text=True, capture_output=True, check=False)
        launch["sbatch_stdout"] = result.stdout
        launch["sbatch_stderr"] = result.stderr
        if result.returncode != 0:
            launch["status"] = "submit_failed"
            launch["failure_type"] = classify_failure(result.stderr + "\n" + result.stdout)
            raise RuntimeError(result.stderr.strip() or result.stdout.strip())
        launch["job_id"] = parse_sbatch_job_id(result.stdout)
        return launch

    def poll(self, launch: dict[str, Any]) -> PollResult:
        job_id = str(launch.get("job_id", ""))
        workdir_check = slurm_workdir_check(job_id, launch, self.paths.root)
        if workdir_check.get("unsafe_stale"):
            return PollResult("unsafe_stale", True, workdir_check)
        if launch.get("status") == "dry_submitted" or job_id.startswith("slurm-dry-"):
            return PollResult("finished", True, {"dry": True})
        sq = subprocess.run(["squeue", "-j", job_id, "-h", "-o", "%T|%R"], text=True, capture_output=True, check=False)
        if sq.returncode == 0 and sq.stdout.strip():
            state, _, reason = sq.stdout.strip().partition("|")
            details = {"squeue_state": state, "reason": reason}
            details.update(slurm_wait_evidence(job_id, launch, self.config))
            return PollResult(state.lower(), False, details)
        sacct = subprocess.run(["sacct", "-j", job_id, "-n", "-P", "-o", "State,ExitCode"], text=True, capture_output=True, check=False)
        details = {"sacct_stdout": sacct.stdout, "sacct_stderr": sacct.stderr}
        status = "finished"
        if "FAILED" in sacct.stdout:
            status = "failed"
        elif "CANCELLED" in sacct.stdout:
            status = "cancelled"
        elif "TIMEOUT" in sacct.stdout:
            status = "timeout"
        return PollResult(status, True, details)

    def cancel(self, launch: dict[str, Any]) -> dict[str, Any]:
        job_id = str(launch.get("job_id", ""))
        if not job_id or job_id.startswith("slurm-dry-"):
            return {"returncode": 0, "status": "nothing_to_cancel"}
        result = subprocess.run(["scancel", job_id], text=True, capture_output=True, check=False)
        return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def get_backend(paths: VibePaths, backend_name: str | None = None) -> ExecutionBackend:
    config = load_config(paths)
    name = backend_name or config.get("execution", {}).get("backend", "local")
    if name == "slurm":
        return SlurmBackend(paths, config)
    if name == "local":
        return LocalBackend(paths, config)
    raise ValueError(f"Unsupported execution backend: {name}")


def parse_sbatch_job_id(stdout: str) -> str:
    for token in stdout.split():
        if token.isdigit():
            return token
    return stdout.strip().splitlines()[-1].strip() if stdout.strip() else ""


def slurm_workdir_check(job_id: str, launch: dict[str, Any], target_root: Path) -> dict[str, Any]:
    expected = str(target_root.resolve())
    launch_workdir = str(launch.get("launch_workdir") or "")
    if launch_workdir and Path(launch_workdir).resolve() != Path(expected).resolve():
        return {
            "unsafe_stale": True,
            "reason": "launch_workdir_target_mismatch",
            "expected_workdir": expected,
            "launch_workdir": launch_workdir,
        }
    if not job_id or job_id.startswith("slurm-dry-"):
        return {"expected_workdir": expected, "launch_workdir": launch_workdir}
    result = subprocess.run(["scontrol", "show", "job", job_id], text=True, capture_output=True, check=False)
    workdir = parse_slurm_workdir(result.stdout)
    details = {
        "expected_workdir": expected,
        "launch_workdir": launch_workdir,
        "slurm_workdir": workdir,
        "scontrol_stderr": result.stderr.strip(),
    }
    if workdir and Path(workdir).resolve() != Path(expected).resolve():
        details.update({"unsafe_stale": True, "reason": "slurm_workdir_target_mismatch"})
    return details


def parse_slurm_workdir(text: str) -> str:
    for token in text.replace("\n", " ").split():
        if token.startswith("WorkDir="):
            return token.partition("=")[2]
    return ""


def slurm_wait_evidence(job_id: str, launch: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    resource = launch.get("resource_request") or {}
    fallback_partitions = list(resource.get("fallback_partitions") or config.get("execution", {}).get("slurm", {}).get("fallback_partitions", []))
    evidence: dict[str, Any] = {
        "squeue_start_stdout": "",
        "squeue_start_stderr": "",
        "requested_walltime": str(resource.get("time", "")),
        "preferred_partition": launch.get("partition", ""),
        "fallback_partitions": fallback_partitions,
    }
    start = subprocess.run(["squeue", "--start", "-j", job_id, "-h", "-o", "%S"], text=True, capture_output=True, check=False)
    evidence["squeue_start_stdout"] = start.stdout.strip()
    evidence["squeue_start_stderr"] = start.stderr.strip()
    max_hours = wait_policy_hours(launch, config)
    if max_hours:
        total_hours = start_plus_run_hours(evidence["squeue_start_stdout"], evidence["requested_walltime"])
        evidence["wait_policy"] = {
            "max_start_plus_run_hours": max_hours,
            "estimated_start_plus_run_hours": total_hours,
            "verdict": "unknown" if total_hours is None else "within_policy" if total_hours <= max_hours else "exceeds_policy",
        }
        evidence["wait_verdict"] = evaluate_wait_policy(launch, config, evidence["wait_policy"], fallback_partitions)
    return evidence


def evaluate_wait_policy(launch: dict[str, Any], config: dict[str, Any], wait_policy: dict[str, Any], fallback_partitions: list[str]) -> dict[str, Any]:
    """Return a conservative monitor-time verdict for a pending Slurm job."""

    max_hours = float(wait_policy.get("max_start_plus_run_hours") or 0)
    current_hours = wait_policy.get("estimated_start_plus_run_hours")
    preferred = str(launch.get("partition") or "")
    if current_hours is None:
        return {
            "verdict": "fallback_check_required",
            "reason": "missing_preferred_start_estimate",
            "preferred_partition": preferred,
            "fallback_checked": fallback_partitions,
        }
    if max_hours and float(current_hours) <= max_hours:
        return {
            "verdict": "keep_preferred_within_window",
            "preferred_partition": preferred,
            "estimated_start_plus_run_hours": current_hours,
            "max_start_plus_run_hours": max_hours,
        }
    fallback_evidence = fallback_completion_estimates(launch, config, fallback_partitions)
    better = [
        row
        for row in fallback_evidence
        if row.get("estimated_start_plus_run_hours") is not None
        and float(row["estimated_start_plus_run_hours"]) < float(current_hours)
        and (not max_hours or float(row["estimated_start_plus_run_hours"]) <= max_hours)
    ]
    if better:
        best = sorted(better, key=lambda row: float(row["estimated_start_plus_run_hours"]))[0]
        return {
            "verdict": "fallback_better_available",
            "preferred_partition": preferred,
            "preferred_estimated_start_plus_run_hours": current_hours,
            "recommended_partition": best.get("partition", ""),
            "recommended_estimated_start_plus_run_hours": best.get("estimated_start_plus_run_hours"),
            "fallback_checked": fallback_evidence,
        }
    return {
        "verdict": "fallback_not_better_keep_preferred",
        "preferred_partition": preferred,
        "preferred_estimated_start_plus_run_hours": current_hours,
        "max_start_plus_run_hours": max_hours,
        "fallback_checked": fallback_evidence,
        "reason": "no_fallback_with_proven_better_completion_window",
    }


def fallback_completion_estimates(launch: dict[str, Any], config: dict[str, Any], fallback_partitions: list[str]) -> list[dict[str, Any]]:
    configured = config.get("execution", {}).get("slurm", {})
    raw_estimates = {}
    for source in [
        configured.get("fallback_partition_estimates", {}),
        (launch.get("resource_request") or {}).get("fallback_partition_estimates", {}),
        launch.get("fallback_partition_estimates", {}),
    ]:
        if isinstance(source, dict):
            raw_estimates.update(source)
    profiles = {row.get("name"): row for row in configured.get("partitions", []) if isinstance(row, dict) and row.get("name")}
    rows: list[dict[str, Any]] = []
    for partition in fallback_partitions:
        estimate = raw_estimates.get(partition)
        source = "configured_estimate" if estimate is not None else ""
        profile = profiles.get(partition, {})
        if estimate is None:
            estimate = profile.get("estimated_start_plus_run_hours", profile.get("expected_start_plus_run_hours"))
            source = "partition_profile" if estimate is not None else "missing"
        if estimate is None:
            estimate = sbatch_test_only_completion_estimate(launch, config, partition)
            source = "sbatch_test_only" if estimate is not None else source
        try:
            hours = float(estimate) if estimate is not None else None
        except (TypeError, ValueError):
            hours = None
            source = "invalid_estimate"
        rows.append({"partition": partition, "estimated_start_plus_run_hours": hours, "source": source})
    return rows


def sbatch_test_only_completion_estimate(launch: dict[str, Any], config: dict[str, Any], partition: str) -> float | None:
    script_path = Path(str(launch.get("sbatch_path") or ""))
    if not script_path.exists():
        return None
    resource = launch.get("resource_request") or {}
    qos = resource.get("qos") or config.get("execution", {}).get("slurm", {}).get("qos", "")
    args = ["sbatch", "--test-only", f"--partition={partition}"]
    if qos:
        args.append(f"--qos={qos}")
    gres = slurm_gres_for_partition(partition, launch, config)
    if gres:
        args.append(f"--gres={gres}")
    args.append(str(script_path))
    result = subprocess.run(args, text=True, capture_output=True, check=False, timeout=10)
    if result.returncode != 0:
        return None
    start_text = parse_sbatch_test_start(result.stdout + "\n" + result.stderr)
    return start_plus_run_hours(start_text, str(resource.get("time", ""))) if start_text else None


def parse_sbatch_test_start(text: str) -> str:
    marker = " to start at "
    if marker not in text:
        return ""
    return text.split(marker, 1)[1].split()[0]


def wait_policy_hours(launch: dict[str, Any], config: dict[str, Any]) -> float:
    resource = launch.get("resource_request") or {}
    raw = resource.get("max_pending_start_plus_run_hours") or config.get("execution", {}).get("slurm", {}).get("max_pending_start_plus_run_hours", 24)
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return 0.0


def start_plus_run_hours(start_text: str, walltime: str) -> float | None:
    start_dt = parse_start_time(start_text)
    if not start_dt:
        return None
    now = datetime.now(start_dt.tzinfo or timezone.utc)
    wait_hours = max(0.0, (start_dt - now).total_seconds() / 3600.0)
    return wait_hours + walltime_hours(walltime)


def parse_start_time(text: str) -> datetime | None:
    value = text.strip().splitlines()[0].strip() if text.strip() else ""
    if not value or value.upper() in {"N/A", "UNKNOWN"}:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo:
        return parsed
    return parsed.astimezone()


def walltime_hours(value: str) -> float:
    try:
        parts = [int(part) for part in value.split(":")]
    except ValueError:
        return 0.0
    if len(parts) == 3:
        return parts[0] + parts[1] / 60.0 + parts[2] / 3600.0
    if len(parts) == 2:
        return parts[0] / 60.0 + parts[1] / 3600.0
    return float(parts[0]) if parts else 0.0


def read_optional_text(path: Path) -> str:
    try:
        return path.read_text()
    except Exception:
        return ""
