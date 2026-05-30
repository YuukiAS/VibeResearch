# Changelog

## Unreleased

## 0.8.4 - 2026-05-30

- Add deterministic cycle-decision synthesis and resource-plan auto-compile
  before run generation when a reviewed cycle still has a placeholder plan.
- Let `generate-runs` recover `blocked_missing_resource_plan` cycles after
  adapter capabilities or framework code have been repaired.
- Route `auto-next` back to `generate-runs <cycle>` for recoverable
  resource-plan blockers instead of treating them as terminal decision dead
  ends.

## 0.8.3 - 2026-05-30

- Separate instrumentation readiness from real-experiment readiness so probe
  capabilities no longer unlock experiment planning by themselves.
- Add real-experiment adapter gap reports that list missing generic evaluator,
  metric contract, baseline/proxy, backend policy, collector, and project
  safety-policy work.
- Add generic real-experiment progress accounting under `.vibe/research/`,
  including countable backend-submitted runs, non-counting failures, and repair
  queue records.
- Add CLI surfaces for `vibe adapter real-gaps` and
  `vibe experiment real-progress`.
- Show daemon, scheduler, active jobs, completed jobs, and next collection
  state more explicitly in scheduler status.

## 0.8.2 - 2026-05-30

- Rewrite the English and Chinese README files with a cleaner project
  narrative, less mixed terminology, and a more mature onboarding structure.
- Add a Codex onboarding operator prompt so a fresh clone can be handed to
  Codex for GitHub install, target-repo bootstrap, blocker questions, answer
  writing, and resumable initialization without manual README-following.
- Ignore local planning/TODO/prompt workspaces and remove concrete planning
  notes from the versioned framework surface so cloned checkouts contain only
  runnable package, docs, and tests.
- Ignore root-level `TODO-v*.md` source requirement drafts to prevent future
  planning notes from being accidentally committed.
- Add a shared bounded discovery walker for bootstrap, adapter discovery,
  script candidate discovery, external dogfood scans, and legacy archive
  import so heavy runtime directories are pruned before traversal.
- Add configurable discovery limits and skip directories through
  `.vibe/config.yaml`, with warnings when discovery is truncated.
- Make bootstrap phase state exclusive so a phase that later passes is removed
  from stale `blocked_phases` or `failed_phases`.
- Refresh `bootstrap status` readiness from the current adapter and policy
  state instead of returning stale readiness JSON after user answers.
- Give generated low-risk instrumentation capabilities default metrics schema
  and artifact trust rules so environment, data, and baseline probes can pass
  contract tests without manual schema edits.
- Ignore local `.vibe/` state in VibeResearch source checkouts.

## 0.8.1 - 2026-05-30

- Add a resumable bootstrap orchestrator with `vibe bootstrap init/run/resume/status/doctor/archive/import-legacy/dogfood/sandbox`.
- Add machine-readable bootstrap state, sessions, readiness reports, readiness dashboard export, script readiness matrix, policy completeness checks, and initialization-aware daily memos.
- Add local ignored `.vibe_dogfood/` sandbox support and a generic dogfood harness for local profiles or external dry-run inspection.
- Add legacy archive/import semantics that preserve old automation state as `imported_unverified` regression evidence rather than trusted scientific evidence.
- Harden script bootstrap and policy gates so placeholder wrappers, missing policies, missing protected metrics, and incomplete autonomy answers block unsafe execution or promotion.
- Document end-to-end bootstrap, local sandbox dogfood, external dogfood, legacy archive/import, and the Plan Mode convention.

## 0.8.0 - 2026-05-30

- Add the bounded autonomous research manager with append-only research events, hypothesis/experiment/evidence snapshots, research decisions, and a budget ledger.
- Add budget, stage-gate, autonomy, memo-language, policy-history, memory-pack, portfolio scheduler, and daily memo workflows.
- Add CLI surfaces for `research`, `hypothesis`, `experiment`, `memory`, `portfolio`, `policy`, `budget`, `memo`, and `dashboard export-research`.
- Gate portfolio scheduling on active adapter capabilities, script/schema readiness, budget caps, autonomy level, trusted evidence, protected metric checks, and duplicate-repeat detection.
- Propagate hypothesis, experiment, policy evaluation, budget reservation, capability, adapter revision, metrics schema, and stage metadata through decisions, compiled resource plans, and generated runs.
- Export dashboard-ready research registry, hypothesis graph, portfolio state, and budget ledger JSON without adding a web UI dependency.
- Update README/Chinese README and focused tests for registry, scheduler, budget, promotion/stop gates, memos, and exports.

## 0.7.1 - 2026-05-30

- Add adapter manifest schema, lifecycle CLI, adapter questions, lint/doctor reports, contract tests, activation provenance, and maturity/readiness gating.
- Bootstrap downstream execution wrappers and script plans during normal init, while keeping generated wrappers draft/untrusted until activation.
- Require active contract-tested capabilities for planner compilation, including new adapter block states and adapter metadata on compiled plans/runs.
- Surface adapter readiness, blockers, contract status, and adapter metadata in Markdown/static dashboard output.
- Update docs and regression tests for adapter onboarding, direct-YAML bypass prevention, readiness gating, and config/toy adapter compatibility.

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
