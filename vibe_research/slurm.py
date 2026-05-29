"""Slurm helpers used by the scheduler boundary.

The first implementation is intentionally dry-run friendly: it can render an
sbatch script and classify common failure text without requiring Slurm on the
developer machine. Actual submission is owned by scheduler commands.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def render_sbatch(manifest: dict[str, Any], *, workdir: Path, output: Path, error: Path) -> str:
    resources = manifest.get("resources", {})
    partitions = resources.get("preferred_partitions") or ["gpu_short"]
    gpu = int(resources.get("gpu", 0) or 0)
    gres = f"gpu:{gpu}" if gpu else ""
    return "\n".join(
        [
            "#!/usr/bin/env bash",
            f"#SBATCH --job-name={manifest.get('run_id', 'vibe')}",
            f"#SBATCH --partition={partitions[0]}",
            "#SBATCH --nodes=1",
            "#SBATCH --ntasks=1",
            f"#SBATCH --cpus-per-task={resources.get('cpus', 1)}",
            f"#SBATCH --mem={resources.get('mem_gb', 4)}G",
            f"#SBATCH --time={resources.get('time', '01:00:00')}",
            f"#SBATCH --output={output}",
            f"#SBATCH --error={error}",
            f"#SBATCH --gres={gres}" if gres else "",
            "",
            "set -euo pipefail",
            f"cd {workdir}",
            manifest.get("entrypoint", {}).get("command", "true"),
            "",
        ]
    )


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

