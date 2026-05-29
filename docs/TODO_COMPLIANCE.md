# TODO.md Compliance Report

Status: implementation-aligned MVP, with live Codex and live Slurm smoke tests
left to the operator environment.

## Implemented Coverage

- Phases 1-3: `vibe init`, root progress files, config/state registries,
  portfolio mode, `portfolio_plan.md`, `portfolio_review.md`,
  `resource_plan.yaml`, multi-run generation, and resource-plan-driven run
  manifests.
- Phases 4-7: Codex-backed planning/review/patch/reflect/revise artifacts,
  local and Slurm backends, branch and merge gates, dry-run, queue, submit,
  monitor, collect, hard-rule validation, and revised-plan gates.
- Phases 8-9: paper search/add/download, PDF checksum and markdown extraction,
  wiki paper/concept/gap/synthesis updates, standardized deep research request
  files, registry tracking, deep report ingest, paper/repo/dataset/risk
  extraction, and blocking `vibe next` behavior.
- Phase 10: leaderboard history, best and best-by-direction updates,
  metric-schema-aware comparison, static Markdown/HTML/SVG timeline, scheduler
  tables, dashboard TODO/status, and local compliance validation.

## Enforcement Points

- `vibe validate-artifact` checks required sections, reviewer verdict enums,
  revised-plan decision enums, and literature/deep research yes/no decisions.
- `vibe validate-hard-rules` checks required cycle/run files, trusted metric
  provenance, merge review, Slurm launch fields, formal paper source/checksum,
  and blocking deep research registry records.
- `vibe submit-queue` enforces dry-run readiness, dependencies, paused
  directions, max parallel jobs, and GPU budget.
- `vibe merge` requires `MERGE_OK` from `vibe merge-review` unless explicitly
  overridden.

## Known Boundaries

- Unit tests use fake Codex/offline mode and dry Slurm launches; they do not
  require network, Codex auth, tmux, or a cluster.
- Real Codex artifact quality depends on the target repo and prompt context.
- Real Slurm partition availability must be verified on the deployment cluster.
- Write Agent remains intentionally out of scope per TODO.md section 20.
