# TODO.md Compliance Report

Status: TODO-aligned local/offline implementation. Live Codex authentication,
network paper search, and real Slurm cluster execution remain environment
validation tasks, not missing framework features.

## Implemented Coverage

- Audit/config/portal: `vibe audit current`, config schema/local/detected files,
  config show/validate/detect/edit, root portal rebuild, no-root init, and
  generated `.vibe/AGENTS*` snippets are implemented.
- Init/install: `vibe init --auto|--minimal|--root-portal|--no-root-portal`
  plus `--goal`, `--background`, `--brief-file`, `--idea`, `--idea-file`, and
  `vibe vendor-runtime` are implemented. Project context is written to
  `.vibe/project/brief.md`.
- Idea pool: maintained `.vibe/ideas/` registry and Markdown views, stable
  `idea_001` IDs, lifecycle commands, raw inbox linking, dashboard intake, and
  revised-plan idea update synchronization are implemented.
- Deep research: request generation from run/cycle/idea, Markdown/PDF ingest,
  `--kind science|workflow|repo|benchmark`, paper DB/wiki/repo queue/idea pool
  updates, and blocking `vibe next` behavior are implemented.
- Portfolio/run/scheduler: multi-run cycle planning, portfolio review gates,
  dry-run-only queue eligibility, dependency/budget checks, Slurm fallback
  provenance, failure classification, trusted metric promotion after
  revised-plan, and cycle revised-plan gating are implemented.
- Dashboard/meeting/dogfood: `vibe dashboard build`, `vibe dashboard serve`,
  read-only static `.vibe/site/index.html`, `vibe export-meeting`, portal docs,
  final reports, and `vibe dogfood` cheap local/mock validation are implemented.

## Enforcement Points

- `vibe validate-artifact` checks required sections, reviewer verdict enums,
  revised-plan decision enums, and literature/deep research yes/no decisions.
- `vibe validate-hard-rules` checks required cycle/run files, trusted metric
  provenance, merge review, Slurm launch fields, formal paper source/checksum,
  and blocking deep research registry records.
- `vibe submit-queue` enforces dry-run readiness, manifest validity, portfolio
  review blocks, dependencies, paused directions, max parallel jobs, and GPU
  budget.
- `vibe merge` requires `MERGE_OK` from `vibe merge-review` unless explicitly
  overridden.
- `vibe next` checks missing project brief, untriaged ideas, deep research
  candidates, blocking deep research, queue/active jobs, run lifecycle gaps,
  and cycle revised-plan gaps.

## Final TODO Check

- No TODO.md framework feature is intentionally left unimplemented for the
  local/offline acceptance path.
- Tests run without Slurm, network, GPU, Codex auth, or long training jobs.
- Real Codex and real Slurm behavior should still be validated in the operator
  environment because those depend on external credentials and cluster state.
