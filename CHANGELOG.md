# Changelog

## Unreleased

## 0.7.0 - 2026-05-30

- Add structured run/cycle decision contracts, validation CLI, and block decisions for missing adapters or repeating evidence.
- Add a generic adapter interface with noop/config/toy adapters and a decision-to-execution compiler that blocks placeholder plans.
- Gate metrics trust and trusted leaderboard updates on schema-valid metrics, non-placeholder commands, provenance, and revised-plan promotion.
- Make offline revised-plan fallback safe by writing explicit block decisions instead of fake progress.
- Surface trust, schema, and block states in status, TODO, leaderboard, timeline, and static dashboard output.
- Document the three-layer architecture with Mermaid diagrams and add v0.7.0 regression tests for compiler, trust, backward-compatibility, and anti-loop behavior.

## 0.6.0 - 2026-05-29

- Add static dashboard build/serve, meeting story-pack export, dogfood report generation, and portal install/usage docs.
- Add init project brief intake, initial ideas, vendor-runtime scaffold, and TODO alignment checks for the installable framework.
- Add final dashboard/meeting/dogfood tests covering the 0.6.0 operator workflow.

## 0.5.0 - 2026-05-29

- Add a maintained `.vibe/ideas/` pool with lifecycle CLI commands, stable `idea_001` IDs, generated Markdown views, and dashboard idea intake.
- Link `vibe idea` and `vibe ask` raw inbox entries into the idea pool, and require idea pool update sections in run/cycle revised plans.
- Add contextual deep research requests from ideas and support Markdown/PDF deep research ingest with idea pool, wiki, paper DB, and repo queue updates.

## 0.4.0 - 2026-05-29

- Add alignment audit, config schema/local/detect/show/validate/edit commands, and detected environment suggestions.
- Add `.vibe/portal/` as the source for generated root mirrors, with rebuild support and no-root/minimal init options.
- Generate `.vibe/AGENTS.md` and `.vibe/AGENTS_SNIPPET.md`, with explicit opt-in root `AGENTS.md` installation.

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
