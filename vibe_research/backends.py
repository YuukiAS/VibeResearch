"""Execution backends for local and Slurm jobs."""

from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import load_config
from .io import ensure_dir, utc_now, write_text
from .manifest import load_manifest
from .paths import VibePaths
from .slurm import choose_partition, classify_failure, render_sbatch


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
        if launch.get("status") == "dry_submitted" or job_id.startswith("slurm-dry-"):
            return PollResult("finished", True, {"dry": True})
        sq = subprocess.run(["squeue", "-j", job_id, "-h", "-o", "%T|%R"], text=True, capture_output=True, check=False)
        if sq.returncode == 0 and sq.stdout.strip():
            state, _, reason = sq.stdout.strip().partition("|")
            return PollResult(state.lower(), False, {"squeue_state": state, "reason": reason})
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


def read_optional_text(path: Path) -> str:
    try:
        return path.read_text()
    except Exception:
        return ""
