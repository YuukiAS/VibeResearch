# Changelog

## Unreleased

## 0.18.1 - 2026-06-01

- Add structured Decision Debt TTL records for WATCH/REFINE outcomes.
- Add `vibe debt list`, `vibe debt validate`, and `vibe debt clear` commands.
- Require REFINE/WATCH debt to name missing evidence, repayment MVE, TTL,
  promotion condition, pivot condition, stop condition, and owner session.
- Connect Reflector outputs to open debt records and Planner diagnostics so new
  plans cannot ignore unresolved high-value debt.
- Clear expired debt after two rounds into STOP negative memory or PIVOT plan
  seeds, and record debt clearances in the Research Registry.

## 0.18.0 - 2026-06-01

- Add a Research Registry and Immune System for route fingerprints and failure
  antigens.
- Add `vibe registry record`, `vibe registry check`, and
  `vibe registry budget-recovery` commands.
- Fingerprint failure anchors, mechanisms, action types, artifact types, metric
  vectors, review verdicts, reflect decisions, and evidence types.
- Connect registry checks to Planner diagnostics and Reviewer rejection so
  renamed repeats are blocked unless they include a new mechanism, source,
  artifact, or evidence path.
- Convert STOP/PIVOT, guardrail regressions, adapter-impossible states, orphan
  knowledge, and metadata-only loops into immune memory.
- Index budget checkpoint, resume, and low-quota interruption records for
  recovery.

## 0.17.1 - 2026-06-01

- Add a Belief Ratchet that converts Reflector outputs into layered evidence
  updates rather than simple success/failure labels.
- Add `vibe ratchet apply` and `vibe ratchet validate` commands.
- Track feasibility, mechanism, metric, robustness, and negative evidence
  separately in ratchet records.
- Update Problem, Mechanism, Experiment, Negative, and Open Debt memory files
  according to evidence type.
- Preserve mechanism evidence without treating it as metric progress, and keep
  one-case evidence from becoming robustness belief.

## 0.17.0 - 2026-06-01

- Add an independent Reflector Session for post-execution interpretation.
- Add `vibe reflector reflect` and `vibe reflector validate` commands.
- Read Executor result manifests, artifact inventory, expected artifacts,
  metric JSON, execution logs, and MVE contracts before writing
  `reflect_report.md`.
- Enforce bounded Reflector verdicts: `PROCEED`, `REFINE`, `PIVOT`, `STOP`, and
  `ASK_HUMAN`.
- Convert MVE success into promotion debt, treat smoke/import success as
  feasibility evidence only, and block PROCEED on missing artifacts or guardrail
  regressions.
- Integrate with 0.16.2 budget runtime so low-quota reflection writes partial
  reflect output and `RESUME.md`.

## 0.16.2 - 2026-06-01

- Add Budget-Aware Session Runtime state in `SESSION_BUDGET_STATE.json`.
- Add `vibe session-budget` commands for initialization, manual Codex `/status`
  refresh, phase guards, checkpoint creation, and zero-cost wait mode records.
- Parse observed `5h limit: ... % left` and `weekly limit: ... % left` status
  text without launching Codex from the framework.
- Generate low-budget checkpoints, root `RESUME.md`, and
  `wait_until_budget_reset.sh` for quota wait recovery.
- Record Slurm job wait versus quota wait as zero-cost state so Codex can stop
  spending reasoning while external work or quota renewal is pending.

## 0.16.1 - 2026-06-01

- Add an Executor Boundary Guard before command execution.
- Add `vibe executor guard` to validate reviewed-manifest, artifact, safety,
  stop, fallback, and failure-report constraints without running commands.
- Verify compiled manifests match `reviewed_plan_manifest.json` approval IDs,
  revision history, mechanism, expected artifact, and stop condition.
- Reject weak artifacts such as README summaries, repo clones, import-success
  outputs, cache paths, metadata-only outputs, and smoke/status markers.
- Block explicit safety red lines for data permission, missing human approval,
  prohibited uploads/deletes/external data, Slurm budget, and resource caps.

## 0.16.0 - 2026-06-01

- Add an Executor Session that runs accepted `execution_manifest.json` files
  through a manifest-driven boundary rather than free-form experiment execution.
- Add `vibe executor run` and `vibe executor validate-result` commands.
- Record execution logs, artifact inventory, result manifests, result reports,
  command provenance, environment details, input assets, and stdout/stderr.
- Block completion when expected MVE artifacts are missing or commands fail,
  writing explicit blocker reports instead.
- Preserve Planner/Reviewer scientific decisions so Executor cannot rewrite the
  failure anchor, hypothesis, mechanism, MVE, or promotion rule.

## 0.15.1 - 2026-06-01

- Add MVE contracts to compiled execution manifests with input asset, minimal
  command, expected artifact, metric/evidence reader, success and failure
  conditions, cost cap, and next promotion rule.
- Add `vibe mve validate` and `vibe mve promote-success` commands.
- Block execution manifests without MVE contracts unless a human-approved MVE
  exception is recorded.
- Add MVE completion checks so missing MVE artifacts cannot close execution.
- Generate next evidence debt after MVE success instead of allowing direct
  mainline success claims.

## 0.15.0 - 2026-06-01

- Add a Compiler Session that turns accepted reviewed plans into auditable
  `execution_manifest.json` packages.
- Add `vibe compiler compile` and `vibe compiler validate` commands.
- Require accepted Reviewer approval before compilation and preserve Reviewer
  criteria, risks, required changes, review trace, and revision history.
- Generate concrete local script and Slurm draft paths, expected artifacts,
  metric readers, evaluation commands, stop conditions, fallback commands, and
  artifact inventory entries.
- Add boundary validation coverage for missing approvals, missing artifact or
  metric readers, preserved reviewer constraints, and valid execution packages.

## 0.14.3 - 2026-06-01

- Add Planner-Reviewer revision packets with failed criteria, required changes,
  optional suggestions, blocking risks, evidence gaps, and resubmission
  deadlines.
- Add `vibe reviewer revision-packet` and `vibe planner resubmit` commands.
- Restrict Planner resubmissions to fields requested by Reviewer and preserve
  revision history on accepted reviewed manifests.
- Add revision loop limit handling so unresolved repeated `REVISE` outcomes
  escalate to `ASK_HUMAN`.
- Record revision provenance in `PLAN_REVISION_REGISTRY.jsonl`.

## 0.14.2 - 2026-06-01

- Add a Reviewer Session that independently reviews Planner draft manifests
  before compilation or execution.
- Add `vibe reviewer review` and `vibe reviewer validate` commands.
- Emit `ACCEPT`, `REVISE`, `REJECT`, or `ASK_HUMAN` review verdicts with
  traceable criteria, required changes, blocking risks, and rejection reasons.
- Write `reviewed_plan_manifest.json` only for accepted plans and record review
  provenance in `PLAN_REVIEW_REGISTRY.jsonl`.
- Add regression coverage for generic U-Net rejection, metadata/smoke-only
  rejection, MVE acceptance, safety `ASK_HUMAN`, and traceable reports.

## 0.14.1 - 2026-05-31

- Add first-class `blocked_missing_artifact_adapter` decisions so artifact-only
  adapter repair diagnoses are not collapsed into missing metric capabilities.
- Preserve explicit artifact-adapter repair directions from cycle reflection and
  revised-plan text in structured blocking questions.
- Treat `reference_only` as a terminal/constraint stance instead of a request to
  collect more metrics.
- Make explicit local artifact commands emit substantive artifact bodies rather
  than placeholder status-only JSON.
- Add regression coverage that artifact-adapter blocks remain distinct from
  `blocked_missing_capability`.

## 0.14.0 - 2026-05-31

- Add a Planner Session draft-plan schema with failure anchor, hypothesis,
  mechanism, minimum experiment, expected artifact, expected belief update,
  compute cost, risk, fallback, and stop condition fields.
- Add `vibe planner draft` and `vibe planner validate` for Planner-only draft
  manifest generation and validation.
- Read kernel context while drafting and surface negative-memory, open-debt,
  smoke-only, confidence-class, and missing-field diagnostics.
- Keep Planner output bounded to draft manifests; it does not approve plans or
  create execution manifests.

## 0.13.2 - 2026-05-31

- Accept clear `reflect` artifact aliases for `## Result interpretation`,
  including `## Result Interpretation` and
  `## Completed Result Interpretation`.
- Keep strict required-section validation for unrelated roles such as
  `revised_plan`.
- Add regression coverage that reflect aliases do not block progress while
  unrelated artifacts remain canonical.

## 0.13.1 - 2026-05-31

- Render `SESSION_PROTOCOL.md` from a structured role catalog covering Planner,
  Reviewer, Compiler, Executor, Reflector, Scout, and Archivist boundaries.
- Add `vibe kernel roles` and `vibe kernel check-role` for role permission
  inspection and preflight validation.
- Block unknown roles with an `ASK_HUMAN` requirement and enforce role-specific
  writable outputs and forbidden actions.
- Add budget-aware preflight behavior that pauses Planner/Reviewer work at low
  quota while allowing Executor checkpoint/closure actions.

## 0.13.0 - 2026-05-31

- Add a session-oriented research kernel under `.vibe/kernel/` with shared
  project kernel, problem state, failure signatures, open debts, negative
  memory, session protocol, and append-only evidence ledger files.
- Create kernel files during `vibe init` and expose `vibe kernel init`,
  `status`, `record-evidence`, and `check-protocol` commands.
- Require traceable evidence records with session role, source, artifact,
  evidence type, belief update, and next action fields.
- Block missing-kernel protocol checks and single-session closed-loop claims
  across plan, review, execute, and reflect duties.

## 0.12.6 - 2026-05-31

- Exclude artifact-only/no-job runs from repeated zero-metric loop-guard
  blocking.
- Preserve run kind and no-job adapter metadata in collected metric history so
  loop guards can distinguish local closure artifacts from model experiments.
- Prevent artifact-only revised-plan text from inferring
  `promote_to_baseline_compare` solely because it mentions a baseline.
- Add regression coverage that repeated artifact-only zero metrics do not block
  downstream artifact-only dependencies.

## 0.12.5 - 2026-05-31

- Allow artifact-only/no-job runs to record logical branches without requiring a
  clean git worktree or creating a real git branch.
- Mark generated local portfolio actions as `artifact_only` with explicit
  `adapter_metadata.no_job` provenance.
- Show logical no-git branch status in run status output.
- Add regression coverage that dirty target repositories can still advance
  artifact-only audit runs to dry-run.

## 0.12.4 - 2026-05-31

- Compile explicit local/no-job portfolio actions into concrete artifact-only
  resource-plan runs instead of falling back to generic placeholders.
- Preserve no-GPU/no-Slurm portfolio intent with `max_gpu_jobs: 0`, local
  backend metadata, and no-job run descriptors.
- Add a resource-plan validation guard when portfolio Markdown contains
  explicit local/no-job actions but the machine plan remains generic.
- Add regression coverage for artifact-only audit/review/decision actions being
  preserved from a corrected portfolio plan.

## 0.12.3 - 2026-05-31

- Add target-scoped advancing locks for `auto-next` and `auto-cycle`, including
  current action tracking and operator-visible lock owner details.
- Expose active advancing lock state in daemon and scheduler status output.
- Reserve Codex call directories atomically so concurrent callers cannot reuse
  the same `callNNN` artifact path.
- Treat untrusted or negative collected metrics and no-promote reflection
  verdicts as authoritative over Markdown-derived promotion decisions.
- Add regression coverage for same-target auto-cycle lock refusal and negative
  untrusted metrics producing stop/redesign instead of promotion.

## 0.12.2 - 2026-05-31

- Compile post-target continuation cycles from active executable adapter
  capabilities when the sustained-round audit target is already complete.
- Repair generic baseline/diagnostic placeholder resource plans into concrete
  capability-backed routes for ongoing downstream improvement.
- Add regression coverage that post-target planning produces multi-route
  executable runs with adapter metadata instead of generic scaffold runs.

## 0.12.1 - 2026-05-31

- Add daemon autonomy status fields for actionable next actions, queued/active
  counts, and monitor-only/`auto_next=false`/dry-submit blockers.
- Add `vibe daemon audit-autonomy` so continuation sessions fail visibly when
  an actionable next step cannot advance under the current daemon mode.
- Return a concrete restart recommendation for autonomous real-submit loops
  instead of silently accepting monitor-only daemon state.

## 0.12.0 - 2026-05-31

- Add generic long-run reliability and soak diagnostics under
  `vibe reliability`.
- Report stale active jobs, state/queue mismatches, stale blockers, budget
  drift, memo freshness, adapter evolution, dashboard export freshness, and
  dual-track health without mutating live jobs.
- Add append-only soak checkpoints and checkpoint comparisons for multi-day
  reliability tracking.
- Emit explicit safe operator recommendations for recovery while filtering out
  live submission, cancellation, destructive git, and deletion commands.
- Add doctor output with a `no_live_mutation` guarantee for dogfood and
  downstream repository soak checks.

## 0.11.1 - 2026-05-31

- Add final convergence policy state with `open_exploration`,
  `dual_track_optimization`, `owned_candidate_focus`,
  `external_regression_only`, and `final_owned_freeze` stages.
- Add `vibe converge` commands for stage transitions, freeze checks,
  late-stage risk gates, external dependency audits, user-approved overrides,
  budget closure, and known-risk review records.
- Require trusted schema-valid evidence, protected-metric stability,
  reproducibility package readiness, budget closure, known-risk review, and
  user approval before final owned freeze.
- Block late-stage protected-metric, reproducibility, core-mechanism, and large
  external-method risks unless an explicit user-approved override applies.
- Classify final dependencies as necessary, reference, regression, removal
  candidate, or owned-core evidence before declaring the main path sufficiently
  owned.

## 0.11.0 - 2026-05-31

- Add `vibe present` exports for narrative, reproducibility, presentation
  tables, framework specification, and complete package manifests.
- Separate traceable evidence-backed claims from speculation/future work and
  preserve negative hypothesis, experiment, evidence, and scout results.
- Export reproducibility rows linking conclusions to experiments, runs,
  metrics, artifacts, adapter revisions, policy revisions, code commits, and
  memos.
- Generate presentation JSON tables for baseline comparison, ablations,
  stage-gate progression, budget usage, hypothesis outcomes, scout traces, and
  external-to-owned transition timelines.
- Build final framework specs from lineage proposals, owned scaffolds, adapter
  internal capabilities, active execution surfaces, dependencies, and optional
  external regression plans.

## 0.10.19 - 2026-05-31

- Prefer actionable current-cycle run lifecycle steps over stale
  real-experiment repair prompts from older cycles.

## 0.10.18 - 2026-05-31

- Prevent offline run-level revise from converting completed runs with
  schema-valid trusted-candidate metrics into `blocked_missing_decision`; it now
  records a conservative non-blocking `collect_more_metrics` decision.

## 0.10.17 - 2026-05-31

- Count real-experiment runs with baseline comparison evidence stored either at
  the top level of `metrics.json` or under nested `metrics.baseline_metrics`
  and `metrics.metric_delta`.

## 0.10.16 - 2026-05-31

- Add direct regression coverage that current-cycle `finished`, `collected`,
  and `reflected` runs complete collect/reflect/revise-plan before cycle-level
  closeout can run.

## 0.10.15 - 2026-05-31

- Report recorded daemon options in daemon status and reject attempts to reuse
  an already-running daemon when requested mode, interval, auto-next, offline,
  dry-submit, or max-step settings differ.

## 0.10.14 - 2026-05-31

- Suppress executable fallback requeue commands when scheduler wait evidence
  says no fallback partition is demonstrably better than the current preferred
  partition.

## 0.10.13 - 2026-05-31

- Exclude non-counting classified runs from daemon status next-collection
  candidates so old explained failures do not appear actionable.

## 0.10.12 - 2026-05-31

- Add regression coverage proving repaired project briefs synchronize stale
  config project context before future prompt packets are built.

## 0.10.11 - 2026-05-31

- Let current-cycle finished, collected, and reflected runs complete their
  collect/reflect/revise output lifecycle before idea refresh or cycle closeout
  actions.
- Add regression coverage for compatible preferred Slurm partitions staying
  ahead of merely available fallback partitions.

## 0.10.10 - 2026-05-31

- Block `vibe dryrun <run_id>` for runs that are already active, submitted,
  pending, or running so repeated dry-runs cannot roll submitted scheduler
  state back to `dryrun_passed`.

## 0.10.9 - 2026-05-31

- Synchronize repaired `.vibe/project/brief.md` goal/background back into
  `.vibe/config.yaml` and `.vibe/config.json` during research initialization.
- Resolve stale placeholder project goal/background research questions once a
  concrete project brief exists.

## 0.10.8 - 2026-05-31

- Add a generic feature-surface regression covering the lineage,
  internalization, scout, dual-track portfolio, owned-framework, and
  optimization CLI entrypoints in an initialized downstream workspace.

## 0.10.7 - 2026-05-31

- Refresh the English and Chinese README files for the current 0.10.x feature
  surface, including lineage, scout evidence gates, dual-track portfolios,
  owned framework alpha scaffolds, champion/challenger optimization, and Slurm
  preferred/fallback policy.

## 0.10.6 - 2026-05-31

- Make Slurm preferred partitions the default submission target when configured;
  fallback availability from `sinfo` alone no longer bypasses the preferred
  partition.
- Allow fallback partition selection only when explicit wait-policy evidence
  recommends a compatible fallback, and record `preferred_partition_selected`
  versus `fallback_selected_after_wait_policy` in launch partition reasons.
- Add operator-facing preferred requeue commands so a pending job that landed on
  a fallback partition can be moved back to the configured preferred partition.

## 0.10.5 - 2026-05-31

- Clear stale blocked state after a recovered multi-route round has closed with
  cycle reflection, cycle revision, terminal route states, and a clean sustained
  round audit.
- Prevent `vibe next` from retaining a stale `Blocked:` prefix after round
  recovery when the correct next action is to plan the next cycle.

## 0.10.4 - 2026-05-31

- Scope repeated decision loop-guard checks to the same target instead of
  treating sibling route decisions as a global repeated loop.
- Allow repeated run-level `collect_more_metrics` when the run already has
  schema-valid collected metrics, preserving the evidence for cycle-level
  comparison.
- Keep true repeated evidence blockers for the same target without valid
  metrics and for repeated untrusted zero-metric history.

## 0.10.3 - 2026-05-31

- Fall back from `squeue` timeout/socket/controller failures to `sacct` when
  monitoring Slurm jobs.
- Parse `sacct` conservatively so running/pending jobs remain active while
  completed, failed, cancelled, and timed-out jobs become terminal.
- Archive stale active jobs when scheduler accounting is unavailable but the
  run already has terminal state or collected/schema-valid metric artifacts,
  preserving carried-forward wait diagnostics only as diagnostic context.

## 0.10.2 - 2026-05-31

- Probe `codex exec --help` before constructing non-interactive Codex commands
  and avoid unsupported approval/search/model flags.
- Default read-role Codex calls to a writable sandbox so local runtimes can
  create session/app-server state while prompts still forbid repository edits.
- When a non-offline Codex call exits nonzero with no usable last message, write
  the current deterministic fallback instead of preserving stale artifacts; run
  revised-plan fallback preserves schema-valid completed metrics as
  `collect_more_metrics`.

## 0.10.1 - 2026-05-31

- Add `vibe optimize` champion/challenger, ablation, regression, optimization
  memory, and external-deemphasis commands for owned-framework optimization.
- Gate champion promotion on trusted evidence, protected metric checks, budget
  policy, and agent rationale.
- Require structured ablations with hypothesis, expected effect, metric target,
  protected-metric risk, and rollback plan; repeated failed ablations produce
  memory warnings.
- Record regression suites that block larger stages on failure and require
  periodic external baseline regression before reducing external exploration.

## 0.10.0 - 2026-05-31

- Add `vibe owned` commands for proposal-bound owned-framework alpha scaffold
  generation, contract checks, shadow execution plans, and design-to-code
  audits.
- Generate downstream `src/<framework>/`, config, tests, docs, metrics export,
  artifact output, and baseline comparison hooks only from approved framework
  proposals, without overwriting user code or violating `AGENTS.md` path
  constraints.
- Add internal capability draft records for owned alpha scaffolds and audit
  hidden external-core calls as `wrapped_external` instead of owned core.

## 0.9.2 - 2026-05-31

- Add dual-track portfolio records for `external`, `internal`, and `hybrid`
  experiments under `.vibe/research/tracks/`.
- Add `vibe portfolio track-plan`, `compare-plan`, `track-audit`,
  `track-budget`, and `track-memo` for generic parallel external/internal
  planning.
- Gate internal promotion on external baselines, comparable metrics, trusted
  evidence, protected metric checks, non-empty design diffs, pseudo-internal
  detection, and configured track budget ratios.

## 0.9.1 - 2026-05-31

- Add offline scout finding, triage, claim, query-context, audit, and memo
  artifacts under `.vibe/research/scout/`.
- Add `vibe scout` commands that classify findings as background,
  candidate method, directly actionable, baseline reference, negative evidence,
  implementation reference, or not relevant using structured quality fields.
- Add claim-evidence and negative-evidence records, and let qualifying scout
  evidence support `shadow_internal` readiness while warning that scout evidence
  does not replace project experiment evidence.

## 0.9.0 - 2026-05-31

- Add generic research lineage registries for external assets, lineage
  relations, internalization decisions, framework proposals, readiness audits,
  and lineage-aware memory under `.vibe/research/lineage/`.
- Add `vibe lineage` and `vibe internalization` commands to register external
  baselines/references, record structured internalization decisions, create
  framework proposals, evaluate readiness for `shadow_internal`, and render
  planning memory.
- Gate internalization readiness on trusted schema-valid evidence, external
  baseline provenance, downstream source targets, metrics schema references,
  minimal internal module scope, remaining upside, and no skipped
  internalization levels.

## 0.8.60 - 2026-05-31

- Add `vibe research sustained-selftest` as an operator-visible end-to-end
  synthetic check for the sustained multi-route research contract.
- Create isolated self-test workspaces under
  `.vibe/selftests/sustained_round/<timestamp>/workspace`, install a toy active
  adapter, seed three active routes and three completed reflected/revised
  rounds, and run `sustained_round_audit()`.
- Persist self-test `latest.json` and `latest.md` summaries and fail the
  command if the audit reports fewer than three completed rounds or any
  structural issue.

## 0.8.59 - 2026-05-31

- Require explicit run scope for fallback requeue execution: `--execute` now
  needs either `--run-id <run>` or `--all`, while dry-run review remains
  non-mutating.
- Add self-contained per-run fallback requeue commands with absolute
  `--target`, `--run-id`, `--execute`, and required approval flags in dry-run
  output and sustained audit resource issues.
- Persist dry-run approval requests under
  `.vibe/scheduler/fallback_requeue_requests/` with `latest.json`,
  `latest.md`, affected jobs, risk text, and exact executable commands.

## 0.8.58 - 2026-05-31

- Link outside-wait-policy fallback diagnostics to a dry-run operator command:
  `vibe next` and sustained audit now recommend
  `vibe scheduler-requeue-fallback --allow-outside-policy` for review.
- Add `scheduler-requeue-fallback` as a command alias for the protected
  fallback requeue review/execution surface while keeping dry-run as the
  default behavior.
- Coerce adapter revision metadata to string when creating experiment records
  so YAML-parsed scalar values cannot break research registry creation.

## 0.8.57 - 2026-05-31

- Add `vibe fallback-requeue` as a provenance-preserving operator surface for
  Slurm fallback recommendations. It is dry-run by default and lists
  eligibility plus blocked reasons.
- Require `--execute` before cancelling/resubmitting jobs, require
  `--allow-outside-policy` for outside-window fallback verdicts, and require
  `--allow-carried-forward` for carried-forward wait evidence.
- Record completed old jobs, new launches, state updates, and timeline events
  when an explicit operator requeue is executed.

## 0.8.56 - 2026-05-31

- Preserve the last valid Slurm wait verdict and wait policy across transient
  unknown monitor polls caused by timeouts, socket errors, or unavailable
  accounting records.
- Recover carried-forward wait evidence from both active job state and per-run
  `monitor.jsonl`, mark it with provenance, and prevent it from triggering
  automatic requeue unless explicitly enabled.

## 0.8.55 - 2026-05-31

- Let `vibe next` surface finished, dry-submitted, collected, or reflected
  sibling runs in the active cycle before falling back to `vibe monitor`.
- Keep active sibling jobs intact while allowing partial multi-route output to
  be collected, reflected, and revised promptly.

## 0.8.54 - 2026-05-31

- Add `vibe external analyze-repo <name>` for read-only cloned repository
  integration analysis: setup files, package roots, likely train/infer/eval
  entrypoints, README excerpts, top-level layout, risks, and safe-integration
  policy.
- Include latest external repo analysis records in cycle prompt context and
  flag cloned repositories without matching integration analysis in sustained
  audit.

## 0.8.53 - 2026-05-31

- Split Slurm fallback evidence into a distinct
  `fallback_better_but_outside_wait_policy` verdict when a fallback is
  materially better than the current partition but still exceeds the configured
  wait-policy window.
- Keep automatic requeue disabled for that verdict while surfacing it in
  sustained audit as a queue-policy issue for operator review.

## 0.8.52 - 2026-05-31

- Add external research resource context to cycle prompt packets, including
  recent source/search records, auto-method-search metadata, cloned external
  repo provenance, bounded README excerpts, and top-level repo file summaries.
- Make that context available to cycle-level reflection and revised planning so
  recorded external resources can inform the sustained research loop.

## 0.8.51 - 2026-05-31

- Treat Slurm socket/controller query failures as non-terminal
  `status=unknown` poll results, preserving query stdout/stderr and avoiding
  fall-through to accounting.
- When a job is absent from `squeue` and `sacct` has no record or fails,
  return non-terminal `slurm_accounting_record_unavailable` instead of marking
  the job finished.

## 0.8.50 - 2026-05-31

- Add a next-action guard for empty preplanned cycles: when all active jobs
  belong to one attempted cycle but `current_cycle_id` points at a different
  empty planned/reviewed cycle, the empty cycle is marked abandoned with
  provenance.
- Restore `current_cycle_id` to the active attempted cycle and keep the next
  action on `vibe monitor` until that round can be collected, reflected, and
  revised.

## 0.8.49 - 2026-05-31

- Make direction pause checks use the latest direction registry row, so later
  promoted/resumed records clear historical pauses.
- Auto-resume only `max failed runs reached` pauses when the same direction has
  prior `missing_required_input` non-counting evidence and the queued
  replacement run's required input files now exist.
- Keep manual stops and unrelated pauses blocked, and surface Slurm sandbox
  socket failures as execution-environment queue issues instead of route
  failures.

## 0.8.48 - 2026-05-31

- Update sustained round audit semantics so blocked runs with non-counting
  classifications count as terminal attempted routes, while all-abandoned
  cycles no longer count as completed sustained rounds.
- Surface current `blocked_missing_capability` state as a sustained-audit issue
  with a next action to run adapter doctor, activate a changed executable
  capability, or repair missing inputs.

## 0.8.47 - 2026-05-31

- Add bounded timeouts to Slurm polling calls (`scontrol`, `squeue`, `sacct`,
  and `squeue --start`) so monitor loops return unknown evidence instead of
  hanging indefinitely.
- Enforce `max_wait_hours_for_fallback` before automatic fallback requeue;
  unknown or out-of-window fallback estimates no longer requeue unless
  `allow_fallback_outside_wait_policy` is explicitly enabled.

## 0.8.46 - 2026-05-31

- Filter scheduler queue rows in `vibe next` through current run state so
  abandoned, missing, or otherwise non-queued runs no longer trigger
  `vibe submit-queue`.
- Make `submit_queue()` drop stale queue rows whose run is missing or no
  longer in `queued` state before attempting backend selection or submission.

## 0.8.45 - 2026-05-31

- Add a multi-route repeat guard to deterministic cycle synthesis: if the
  active real-experiment capability set exactly repeats the latest
  non-counting multi-route cycle, synthesis now blocks with
  `blocked_missing_capability`.
- The block asks for a changed executable capability, repaired non-counting
  cause, or explicit adapter decision before repeating the same route set.

## 0.8.44 - 2026-05-31

- Clear stale `blocked_missing_decision` next-action blocks when the referenced
  run or cycle belongs to a cycle that already has reflection and revision
  artifacts.
- Treat blocked runs with a non-counting classification as terminal for this
  stale-block cleanup path, and let abandoned closed cycles continue to the
  next planning cycle.

## 0.8.43 - 2026-05-31

- Guard metric collection for dry-submitted launches: `collect` now ignores
  configured external metrics files when `launch.json` records
  `dry_submitted` or a `slurm-dry-*` job id.
- Record `provenance.dry_launch_metrics_ignored` plus the ignored metrics path
  so stale metrics cannot become countable real-experiment evidence.

## 0.8.42 - 2026-05-31

- Make autonomous submission flags fail closed: `--dry-submit` remains the
  default recording mode, while real backend submission now requires explicit
  `--real-submit`.
- Add `vibe research sustained-next` and `vibe research sustained-cycle`
  aliases with the same explicit dry/real submission semantics.
- Update daemon and auto-cycle entrypoints to pass the effective dry-submit
  value as `dry_submit and not real_submit`.

## 0.8.41 - 2026-05-31

- Add generic Slurm partition/runtime compatibility checks driven by declared
  partition metadata, runtime requirements, and resource-level allow/exclude
  lists, without hard-coding cluster-specific GPU partition names.
- Filter Slurm fallback recommendations through compatibility checks while
  preserving skipped incompatible candidates and reasons in wait evidence.
- Make `vibe next` and sustained round audits block on unrepaired real
  experiment failures before planning another round or recommending unrelated
  metric collection.

## 0.8.40 - 2026-05-31

- Add generic downstream adapter dependency readiness checks for declared
  required files, directories, paths, local repositories, Python modules,
  dataset manifests, and metrics caches.
- Surface missing dependency issues in adapter readiness and contract-test
  results using downstream-adapter wording, without introducing any
  project-specific model integration.
- Block Slurm queue submission when the selected adapter capability has missing
  declared downstream dependencies unless the run or capability explicitly
  records a dependency override.

## 0.8.39 - 2026-05-31

- Add sustained multi-route round support: default portfolio candidates now
  diversify across active hypotheses and executable capabilities, deterministic
  cycle synthesis can emit multi-capability resource plans, and `vibe next`
  monitors fragmented active jobs before planning another cycle.
- Make bounded method search cycle-aware: searches are deduplicated within one
  context, rerun for new cycle contexts, and offline skips no longer block a
  later online search.
- Add richer cycle reflection/revision scaffolds, `vibe research sustained-audit`
  for reflected multi-route round checks, and `vibe external clone-repo` to
  acquire external repositories with provenance under `.vibe/research/`.

## 0.8.38 - 2026-05-31

- Promote semantic onboarding decisions into the default initialization question
  flow: required project goal, project background, optional initial ideas,
  preferred/fallback Slurm partitions, GRES templates, and the first
  adapter/script execution surface.
- Update Codex onboarding instructions so agents must stop and ask users for
  these subjective decisions instead of filling them in from heuristics.
- Harden daemon status for tmux-managed shell loops by recording a
  `VIBE_DAEMON_TARGET` sentinel, prefer dry-run contract outputs over real
  experiment outputs, and tolerate root portal rebuild races.

## 0.8.37 - 2026-05-30

- Expand Slurm wait-policy comparisons to include the current launch partition,
  original preferred partitions, configured default partition, and fallback
  partitions, while never recommending a requeue to the same current partition.
- When `squeue --start` cannot estimate the current job, evaluate
  `sbatch --test-only` candidates and conservatively requeue to a proven better
  candidate within policy or materially better candidate with explicit evidence.

## 0.8.36 - 2026-05-30

- Let real-progress classify failed/cancelled real experiments with
  `superseded_by`/replacement metadata as non-counting but already classified,
  so they no longer remain unresolved repair blockers.
- Prefer monitoring/collection when replacement real experiments are already
  queued, submitted, pending, or running.

## 0.8.35 - 2026-05-30

- Treat `.vibe/config.json` as a generated mirror/fill source and let human
  `.vibe/config.yaml` edits override stale JSON values during `load_config`.
- Add a regression test proving Slurm partition edits in YAML take precedence
  over stale JSON mirror values.

## 0.8.34 - 2026-05-30

- Promote initialization policy decisions into the default research question
  flow: resource mode, queue wait limits, ordinary experiment runtime caps,
  final delivery/submission runtime caps, GPU submission permission, budget
  caps, autonomy level, primary metric schema, and protected metrics.
- Add `vibe research answer <question_id> --answer ...` so Codex can record
  user-provided answers without inventing them or manually editing JSONL files.
- Make bootstrap question gating include open research policy questions, not
  only adapter questions and policy-file completeness.

## 0.8.33 - 2026-05-30

- Remove built-in partition-name-to-GRES assumptions from Slurm rendering; GPU
  model-specific GRES strings now come only from run resources, project config,
  or explicit partition profiles.
- Add `vibe init --partition-gres partition=gres-template` so onboarding agents
  can write target-cluster GRES policy during initialization.
- Initialize GPU/Slurm resource onboarding for every project by writing
  `.vibe/resources/detected.yaml`, `.vibe/resources/policy_questions.yaml`, and
  `.vibe/resources/README.md` during `vibe init`.
- Split ordinary experiment runtime caps from final delivery/submission runtime
  caps via `--delivery-max-run-hours` and `--delivery-max-epochs`; delivery caps
  only apply to runs explicitly marked as delivery/submission/final maturity.
- Extend config detection to parse `sinfo -h -o "%P %G"` into suggested Slurm
  partition profiles without automatically trusting or applying them.
- Update onboarding docs to require target-cluster Slurm/GPU discovery before
  choosing preferred/fallback partitions, wait limits, runtime caps, and epoch
  caps.

## 0.8.32 - 2026-05-30

- Normalize null adapter capability mapping/list fields during partial manifest
  recovery so blank YAML fields such as `entrypoint:` or `trust_checks:` cannot
  crash adapter readiness, dashboard, or status commands.

## 0.8.31 - 2026-05-30

- Render Slurm `--gres` with partition-specific GPU names for known A100 and
  Volta partitions, while still allowing config/resource overrides.
- Rewrite adapter commands that invoke `python -m vibe_research.*` to the
  current configured framework interpreter, avoiding stale external supervisor
  environments in freshly cloned targets.
- Add an explicit opt-in `execution.slurm.auto_requeue_to_better_fallback`
  policy that cancels and re-submits pending Slurm jobs only when monitor
  evidence proves a fallback partition has a better completion window.

## 0.8.30 - 2026-05-30

- Add init-time scheduler resource policy options for preferred/fallback Slurm
  partitions, maximum pending start-plus-run wait hours, per-experiment
  walltime caps, mature long-run caps, and epoch caps.
- Normalize adapter-generated run resources so preferred/fallback partitions are
  preserved, normal queued jobs are not strict-pinned away from fallback
  selection, and generated runs carry bounded runtime limits.
- Export runtime caps into Slurm scripts as `VIBE_MAX_RUN_HOURS` and
  `VIBE_MAX_EPOCHS` for project adapters that honor framework limits.
- Keep recent bootstrap phase records in daily memos across UTC/local date
  boundaries so onboarding progress is not hidden immediately after bootstrap.

## 0.8.29 - 2026-05-30

- Repair existing zero-byte cycle portfolio plans during monitor steps by
  regenerating the deterministic plan template with current idea-pool context.

## 0.8.28 - 2026-05-30

- Preserve existing deterministic artifacts when an online Codex call returns
  an empty final message, preventing zero-byte portfolio plans from erasing
  idea-pool context.

## 0.8.27 - 2026-05-30

- Allow bounded prequeue planning while active jobs exhaust scheduler capacity,
  so the next real experiment can be planned, dry-run, and internally queued
  without submitting over budget.
- Return `vibe monitor` for queued jobs while capacity is still full, then
  resume `vibe submit-queue` once capacity frees.

## 0.8.26 - 2026-05-30

- Route `needs_literature_refresh` idea-pool entries through a new
  `lit-refresh-idea` action so online method-search ideas can become
  actionable follow-up run candidates.
- Include actionable idea-pool entries in portfolio plan templates, making
  online method-search outputs visible to subsequent cycle planning.
- Preserve an existing generated portfolio plan during offline planner fallback
  so the template's idea-pool context is not overwritten.
- Preserve the initialized portfolio template in offline planning so local
  plan-cycle checks still carry idea-pool context.

## 0.8.25 - 2026-05-30

- Add a bounded `auto-method-search` path that derives a project-aware method
  query, records source provenance, stores paper candidates, and seeds idea-pool
  entries from online results.
- Let online `auto-cycle` monitor passes trigger that search once while jobs are
  pending, while preserving offline mode as no-network.
- Query Semantic Scholar, OpenAlex, and arXiv by default so a single source
  failure does not suppress method-candidate discovery.

## 0.8.24 - 2026-05-30

- Use a conservative default Slurm wait policy of 24 start-plus-run hours when
  no run or config override is provided.
- Parse naive Slurm start estimates in the local timezone instead of treating
  them as UTC.
- Probe fallback partitions with `sbatch --test-only` when static fallback
  estimates are unavailable, and keep that evidence in wait verdict details.
- Render scheduler wait verdicts from `wait_verdict` with a fallback to
  `wait_policy.verdict`.

## 0.8.23 - 2026-05-30

- Treat `monitored` as a terminal result for one `auto-cycle` iteration so a
  daemon performs one scheduler poll before sleeping instead of looping through
  the monitor action repeatedly.

## 0.8.22 - 2026-05-30

- Rank active real-experiment capabilities by prior generated/submitted run
  count before resource demand and id when synthesizing cycle decisions.
- This keeps deterministic behavior while rotating across unused active
  capabilities instead of repeatedly selecting the first capability.

## 0.8.21 - 2026-05-30

- Let `vibe next` continue planning when active jobs exist but scheduler job/GPU
  capacity is still available and no queued work is waiting.
- Preserve conservative monitoring when active jobs exhaust
  `max_parallel_jobs` or `max_gpu_jobs`.

## 0.8.20 - 2026-05-30

- Prefer run-level Slurm `resources.account` and `resources.qos` over global
  Slurm defaults when rendering sbatch scripts.
- Start tmux daemon panes with `-c <target_root>` so pane cwd, recorded target,
  and command target all prove the same checkout binding.
- Preserve framework importability inside daemon tmux shells by exporting the
  framework root through `PYTHONPATH` in the daemon command and recording it in
  daemon state.

## 0.8.19 - 2026-05-30

- Add explicit regression coverage for branchless adapter-backed real
  experiment runs in dirty target worktrees, including branch-skip metadata and
  empty patch recording.

## 0.8.18 - 2026-05-30

- Add regression coverage that `submit-queue --dry` without an explicit backend
  uses each queued run's generated `entrypoint.type`, preserving Slurm-backed
  adapter runs even when the global default backend is local.

## 0.8.17 - 2026-05-30

- Clear stale top-level block reasons when creating a new current cycle so a
  resolved or abandoned run-level block cannot prevent the new cycle from
  review/generation.
- Make `compute_next_action()` treat top-level `blocked_reason` as active only
  when the state is blocked or the next action is an explicit decision-show
  block.

## 0.8.16 - 2026-05-30

- Preserve adapter capability `entrypoint.type` when compiling resource plans
  and generating runs, so Slurm-backed capabilities stay Slurm-backed instead
  of silently becoming local runs.
- Carry entrypoint type through multi-run compiled plans.
- Select the submission backend from each run's generated `entrypoint.type`
  when the operator did not pass an explicit backend override.
- Treat adapter-backed real-experiment runs as already executable after branch
  recording, so the workflow can proceed directly to dry-run without requiring
  a repo code patch for wrapper-driven experiments.

## 0.8.15 - 2026-05-30

- Select synthesized cycle decision types from the chosen active capability's
  supported executable decisions instead of assuming `collect_more_metrics`.
- Prefer training and long-run capabilities through `launch_gpu_gate`,
  evaluation and metric capabilities through `collect_more_metrics`, and
  baseline comparison through `promote_to_baseline_compare` when a baseline
  target is declared.
- Make default research portfolio candidates use the selected capability's
  supported executable decision type.

## 0.8.14 - 2026-05-30

- Add repo-declared adapter profiles (`.viberesearch/profile.yaml`,
  `.vibe_profile.yaml`, `viberesearch.profile.yaml`, or `viberesearch.yaml`)
  that are matched by durable project evidence instead of checkout basename.
- Let matched profiles fill known adapter answers, merge deterministic
  capabilities, write profile-sourced contract-test records, and recover
  `blocked_missing_adapter` when the declared contracts are complete.
- Add `vibe adapter profile-detect` and `vibe adapter profile-apply` for
  explicit inspection, while allowing init/next-action recovery to apply a
  matched profile automatically.

## 0.8.13 - 2026-05-30

- Bind daemon session names to a hash of the target root and make
  `daemon start` reject an already-running session whose pane path, recorded
  target, or captured command target points at a different checkout.
- Report daemon target-root binding fields in `daemon status`.
- Record launch workdirs for local and Slurm jobs, and mark Slurm active jobs
  as `unsafe_stale` when their recorded or scheduler-reported `WorkDir` does
  not match the current target root.

## 0.8.12 - 2026-05-30

- Start tmux daemons through an explicit shell invocation
  (`/usr/bin/bash -lc` when available, otherwise `sh -lc`) so the requested loop
  command is executed reliably instead of leaving an idle interactive pane.
- Record the daemon shell in `.vibe/state/daemon.json` for launch debugging.

## 0.8.11 - 2026-05-30

- Launch daemon loops with the same Python interpreter that invoked the CLI
  instead of relying on `python` from the tmux shell `PATH`.
- Record the daemon interpreter path in `.vibe/state/daemon.json` for
  debugging environment mismatches.

## 0.8.10 - 2026-05-30

- Make `vibe daemon start` capable of running the full `auto-cycle` state
  machine loop instead of only `monitor --loop --auto-next`.
- Add daemon start flags for `--mode auto-cycle|monitor`, `--online/--offline`,
  `--dry-submit/--real-submit`, and `--max-steps`, and record the selected loop
  policy in `.vibe/state/daemon.json`.

## 0.8.9 - 2026-05-30

- Add conservative Slurm wait-policy verdicts during monitor polling, including
  explicit keep-preferred, fallback-check, fallback-better, and
  fallback-not-better outcomes.
- Persist the latest active-job poll details back into active scheduler state
  and each run's `launch.json` so status and dashboard output can explain why a
  pending job is still waiting.

## 0.8.8 - 2026-05-30

- Compile one run per matching active adapter capability when multiple
  capabilities support the same executable decision and the decision does not
  explicitly select a single direction.
- Preserve single-capability compilation when `selected_direction` names a
  specific capability or task.

## 0.8.7 - 2026-05-30

- Preserve `vibe monitor` as the next action while scheduler active jobs exist
  so cycle compilation cannot overwrite active-job control state with stale
  run-generation actions.
- Render status with active scheduler jobs as the authoritative next action.
- Record Slurm pending wait evidence from `squeue --start`, requested walltime,
  and optional start-plus-run wait policy verdicts during polling.

## 0.8.6 - 2026-05-30

- Add a generic strict preferred Slurm partition policy through
  `resources.strict_preferred_partition` or `resources.prefer_configured_partition`.
- When strict preferred partition policy is set, select the first configured
  preferred partition even if `sinfo` does not list it, and record
  `strict_preferred_partition` as the selection reason.

## 0.8.5 - 2026-05-30

- Scope `next` and `auto-next` run-level actions to the current cycle while it
  has non-terminal runs, so historical bootstrap or instrumentation runs cannot
  preempt the active experiment cycle.
- Preserve historical run inspection after the current cycle is terminal.

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
