# Changelog

## Unreleased

## 0.3.0 - 2026-05-29

- Tighten TODO.md alignment with Codex-backed `plan-cycle`/`patch`, resource-plan-driven run generation, verdict gates, scheduler dependency and GPU-budget waits, Slurm partition fallback provenance, trusted metric provenance, PDF markdown extraction, richer wiki/deep-research ingest, and a compliance report.

## 0.2.0 - 2026-05-29

- Add config migration, manifest validation, operator next-action gating, and merge-review enforcement.
- Add local and Slurm execution backend abstractions with local `tmux`/`Popen` support, Slurm sbatch rendering, polling, cancellation, partition selection, and failure classification.
- Add `monitor --loop`, `daemon start/stop/status/logs`, scheduler status, cancel, and backend-selectable `submit-queue`.
- Add paper DB/search/download/wiki helpers and stronger deep-research ingest into wiki, paper records, and inbox triage.
- Add Codex prompt/artifact helper commands for bounded artifact generation.
- Execute Codex CLI through `codex exec` for artifact generation, with call logs under `.vibe/codex_calls/` and deterministic `--offline` fallback.
- Add artifact validators, hard-rule validation, `auto-next`, `auto-cycle`, scheduler explanation, direction status commands, and fake-Codex pytest coverage.

## 0.1.0 - 2026-05-29

- Add the initial `vibe-research` Python package and `vibe` CLI.
- Implement target-repo `.vibe/` initialization, root progress files, config, registries, prompts, and templates.
- Add cycle/run planning scaffolds, idea/directive inbox, scheduler queue, dry-run, submission, monitor, collect, reflect, and revised-plan commands.
- Add leaderboard, dashboard, timeline Markdown/HTML/SVG rendering, Slurm helpers, and Codex artifact-boundary helpers.
- Add smoke-style CLI tests for the first end-to-end workflow.
