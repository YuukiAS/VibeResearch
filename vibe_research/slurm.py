"""Slurm helpers used by the scheduler boundary.

The first implementation is intentionally dry-run friendly: it can render an
sbatch script and classify common failure text without requiring Slurm on the
developer machine. Actual submission is owned by scheduler commands.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def render_sbatch(
    manifest: dict[str, Any],
    *,
    workdir: Path,
    output: Path,
    error: Path,
    partition: str | None = None,
    config: dict[str, Any] | None = None,
) -> str:
    resources = manifest.get("resources", {})
    config = config or {}
    slurm = config.get("execution", {}).get("slurm", {}) or config.get("slurm", {})
    partitions = resources.get("preferred_partitions") or [slurm.get("default_partition", "gpu_short")]
    selected_partition = partition or partitions[0]
    gpu = int(resources.get("gpu", 0) or 0)
    gres = f"gpu:{gpu}" if gpu else ""
    account = slurm.get("account", "")
    qos = slurm.get("qos", "")
    return "\n".join(
        [line for line in [
            "#!/usr/bin/env bash",
            f"#SBATCH --job-name={manifest.get('run_id', 'vibe')}",
            f"#SBATCH --partition={selected_partition}",
            "#SBATCH --nodes=1",
            "#SBATCH --ntasks=1",
            f"#SBATCH --cpus-per-task={resources.get('cpus', 1)}",
            f"#SBATCH --mem={resources.get('mem_gb', 4)}G",
            f"#SBATCH --time={resources.get('time', '01:00:00')}",
            f"#SBATCH --output={output}",
            f"#SBATCH --error={error}",
            f"#SBATCH --gres={gres}" if gres else "",
            f"#SBATCH --account={account}" if account else "",
            f"#SBATCH --qos={qos}" if qos else "",
            "",
            "set -euo pipefail",
            f"cd {workdir}",
            manifest.get("entrypoint", {}).get("env_setup", ""),
            manifest.get("entrypoint", {}).get("command", "true"),
            "",
        ] if line]
    )


def select_partition(manifest: dict[str, Any], config: dict[str, Any]) -> str:
    resources = manifest.get("resources", {})
    preferred = list(resources.get("preferred_partitions") or [])
    fallback = list(resources.get("fallback_partitions") or [])
    execution_slurm = config.get("execution", {}).get("slurm", {})
    if not preferred:
        preferred = [execution_slurm.get("default_partition", "gpu_short")]
    candidates = preferred + [p for p in fallback if p not in preferred]
    profiles = {row.get("name"): row for row in execution_slurm.get("partitions", []) if row.get("name")}
    if not profiles:
        return candidates[0]
    ranked = sorted(candidates, key=lambda name: profiles.get(name, {}).get("priority", 0), reverse=True)
    return ranked[0]


def classify_failure(text: str) -> str:
    lowered = text.lower()
    if "out of memory" in lowered or "oom" in lowered:
        return "oom"
    if "time limit" in lowered or "timeout" in lowered:
        return "timeout"
    if "nan" in lowered:
        return "nan"
    if "importerror" in lowered or "modulenotfounderror" in lowered:
        return "import_error"
    if "permission denied" in lowered or "operation not permitted" in lowered:
        return "permission"
    if "quota" in lowered or "no space left" in lowered:
        return "quota"
    return "unknown"
