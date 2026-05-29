# VibeResearch

VibeResearch is a repo-specific sustained research orchestration framework.
Run `vibe init` inside a target repository to create a `.vibe/` control layer,
root-level progress files, and a deterministic runner/scheduler boundary.

The framework intentionally separates LLM-generated planning artifacts from
trusted execution state. Codex can write plans, reviews, manifests, patches,
reflections, and revised plans; local Python commands own dry-runs, Slurm
submission, monitoring, collection, provenance, dashboards, and merge records.

```bash
python -m vibe_research.cli init --target /path/to/repo
python -m vibe_research.cli status --target /path/to/repo
python -m vibe_research.cli next --target /path/to/repo
```

## Execution Backends

VibeResearch supports two execution backends:

- `local`: launches jobs locally, preferring `tmux` when available and falling
  back to `subprocess.Popen`.
- `slurm`: renders an sbatch script, submits with `sbatch`, monitors with
  `squeue`/`sacct`, and records Slurm provenance in `launch.json`.

Use them through:

```bash
vibe submit-queue --backend local
vibe submit-queue --backend slurm
vibe monitor --loop --auto-next
vibe daemon start
```

Codex CLI can generate artifacts directly. Normal planning commands also call
Codex unless `--offline` is supplied:

```bash
vibe plan-cycle --offline
vibe codex-plan c001
vibe codex-review r001_baseline_check
vibe patch r001_baseline_check
vibe codex-reflect r001_baseline_check
vibe codex-revise r001_baseline_check
```

Use `--offline` on Codex-backed commands for deterministic tests or machines
without Codex auth. Full-loop automation is available through:

```bash
vibe auto-next --offline
vibe auto-cycle --offline --dry-submit
vibe validate-hard-rules
```

`vibe validate-hard-rules` is the local TODO.md compliance gate. It checks
required cycle/run artifacts, merge gates, Slurm provenance, trusted metric
provenance, and blocking deep-research state.

Paper/wiki and deep-research helpers are local-first:

```bash
vibe paper-search "segmentation topology" --offline --add-candidates
vibe paper-add "Example Paper" --source-url https://arxiv.org/abs/0000.0000
vibe paper-download p_example-paper https://example.org/paper.pdf
vibe wiki-ingest p_example-paper
vibe deep-request-cycle c001 "route selection" --blocking
```

Paper download records a local PDF checksum and creates a markdown extraction
stub or `pdftotext` extraction. Wiki ingest updates paper notes plus concept,
gap, and synthesis entrypoints.
