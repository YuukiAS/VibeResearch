# Next TODO.md Implementation Plan

This plan aligns the current `0.3.0` VibeResearch baseline to the newer
`TODO.md`. It is intentionally staged so later implementation can proceed in
small release commits rather than one large, hard-to-review patch.

Do not modify user-edited `TODO.md` or `TODO-v1.md` while implementing this
plan.

## Summary

Treat `0.3.0` as the current baseline. Implement the new TODO in three staged
releases:

- `0.4.0`: audit, config, root portal, AGENTS snippet.
- `0.5.0`: project brief/init intake, idea pool, and deep research from idea.
- `0.6.0`: static dashboard, meeting export, dogfood reports.

Before every commit, update `CHANGELOG.md`.

## Phase 0: Preflight

- Check `git status` and preserve unrelated user changes.
- Run baseline tests: `env_vibe_research/bin/python -m pytest -q`.
- Confirm current package version is `0.3.0`.
- Keep authoritative generated state under `.vibe/`.
- Root files must be generated portals/mirrors only, never unique state.

## 0.4.0: Audit, Config, Portal

### Alignment Audit

- Add `vibe audit current`.
- Write `.vibe/reports/dev/current_alignment_audit.md`.
- Cover init, config, scheduler, Slurm, cycle, run, revised plan, deep research,
  dashboard, idea pool, meeting export, tests, root portal, and AGENTS snippet.

### Config System

- Add `.vibe/config.schema.json`.
- Add `.vibe/config.local.yaml` support for local-only settings.
- Add `vibe config show`.
- Add `vibe config validate`.
- Add `vibe config detect`.
- Add `vibe config edit`.
- `detect` should probe git, Python environment, Slurm binaries, `sinfo`,
  `squeue`, `sacct`, `nvidia-smi`, GPU model/count, repo root, and common
  data/result directories.
- Write detected suggestions to `.vibe/config.detected.yaml`; do not auto-merge
  them into `config.yaml`.

### Root Portal

- Add `.vibe/portal/` as the source for root mirrors.
- Add `vibe portal build`.
- Update `vibe init` with:
  - `--auto`
  - `--minimal`
  - `--root-portal copy|symlink|none`
  - `--no-root-portal`
  - `--install-agents-snippet`
- Default root files must begin with a generated/mirror notice.
- `vibe init --minimal --no-root-portal` must create only `.vibe/`.
- Generate `.vibe/AGENTS.md` and `.vibe/AGENTS_SNIPPET.md`.
- Never modify root `AGENTS.md` unless `--install-agents-snippet` is explicit.

### 0.4.0 Tests

- Config schema validation.
- Mocked config detect with fake Slurm/GPU commands.
- Default portal creation.
- `--no-root-portal` init.
- Portal rebuild after deleting root mirrors.
- AGENTS snippet generation.

## 0.5.0: Idea Pool and Deep Research From Idea

### Project Brief and Init Intake Enhancement

- Add a required project goal/background concept for normal initialization,
  without disrupting the already-running `0.4.0` init/config/portal work.
- Add or finalize `.vibe/project/brief.md` as the authoritative project brief.
- Add `vibe init --goal "..." --background "..."`.
- Add `vibe init --brief-file PROJECT_BRIEF.md`.
- Add repeatable `vibe init --idea "..."`.
- Add `vibe init --idea-file initial_ideas.md`.
- For normal non-minimal init, require goal/background through flags,
  brief-file, or interactive prompt.
- For `--minimal`, allow skeleton creation but mark project brief as missing and
  make `vibe next` / dashboard show that project goal/background must be filled.
- Initial ideas are optional. When provided, write them first to raw inbox, then
  create or link corresponding idea pool entries with `source=init`.
- Ensure Codex planning, Reviewer prompts, deep research requests, dashboard,
  and meeting export include the project brief context.

### Idea Pool

- Add `.vibe/ideas/`.
- Add:
  - `registry.jsonl`
  - `pool.md`
  - `active.md`
  - `deep_research_candidates.md`
  - `backlog.md`
  - `rejected.md`
  - `archive.md`
- Add stable idea IDs: `idea_001`, `idea_002`, etc.
- Track source, status, priority, confidence, linked evidence, rationale,
  current evidence, next action, and archive/rejection reason.

### Idea CLI

- Add `vibe ideas list`.
- Add `vibe ideas triage`.
- Add `vibe ideas promote <idea_id>`.
- Add `vibe ideas reject <idea_id>`.
- Add `vibe ideas archive <idea_id>`.
- Add `vibe ideas clean`.
- Add `vibe ideas build-deep-request <idea_id>`.
- Preserve the existing lightweight prompt intake commands:
  - `vibe idea "free text research idea"`
  - `vibe ask "free text question"`
- Ensure both commands create raw inbox entries first, then link or triage those
  entries into the maintained idea pool.

### Revised Plan Integration

- Keep `vibe idea` writing raw inbox.
- Add or link idea pool entries during triage.
- Require `## Idea pool update` in run-level and cycle-level revised plans.
- `revise-plan` and `revise-cycle` should sync actionable, new,
  deep-research, rejected, archived, and superseded idea updates into the idea
  pool.

### Dashboard Idea Intake

- Current baseline already supports text ideas through CLI (`vibe idea`) and
  mirrors recent new/triaged ideas into `.vibe/dashboard/TODO.md` and
  `VIBE_TODO.md`.
- Current baseline does not provide a dashboard panel or form for submitting a
  text prompt.
- Add an "Idea Intake" panel to the dashboard that shows:
  - the exact command `vibe idea "..."`;
  - recent raw inbox prompts;
  - recently triaged idea pool entries;
  - candidate next actions for each idea.
- Keep the first implementation read-only. Do not create a public writable
  dashboard endpoint by default.
- If a writable local dashboard action is later added, require localhost-only
  binding or a local token; do not assume cloudflared/public safety.

### Deep Research From Idea

- Add `vibe deep-request-from-idea <idea_id>`.
- The generated request must read:
  - idea content
  - relevant run/cycle evidence
  - leaderboard and best-by-direction
  - wiki pages
  - paper DB summaries
  - repo architecture summary
  - scheduler/resource constraints
  - open questions
  - reviewer opinions
  - revised plans
- Marking an idea as `needs_deep_research` must not automatically create a
  deep research request. User or CLI action must trigger request generation.

### Deep Research Ingest

- `vibe ingest-deep-research` should support markdown and PDF.
- Add `--kind science|workflow|repo|benchmark`.
- PDF extraction should use PyMuPDF when available; no OCR.
- Ingest should update paper DB, raw repo queue, wiki pages, idea pool, inbox
  triage, dashboard, timeline, and revised plan/cycle revised plan when
  decisions change.

### 0.5.0 Tests

- Init with goal/background writes `.vibe/project/brief.md`.
- Init with `--brief-file` imports the brief.
- Init with one or more `--idea` writes raw inbox entries and idea pool entries.
- Minimal init without brief marks project brief as missing and surfaces it in
  `vibe next` or dashboard.
- Idea lifecycle.
- Idea clean dedupe, stale, and archive behavior.
- Revised plan idea update.
- `deep-request-from-idea`.
- Markdown deep research ingest.
- PDF ingest with generated tiny PDF or mocked extractor.
- Blocking vs nonblocking deep research next-action.

## 0.6.0: Dashboard, Meeting Export, Dogfood

### Static Dashboard

- Add `vibe dashboard build`.
- Build `.vibe/site/index.html`.
- Use dashboard status, timeline, leaderboard, cycles, runs, ideas, research
  registry, scheduler state, and artifact paths.
- Include cycle cards, run cards, direction board, scheduler/Slurm status,
  leaderboard, timeline, idea pool panel, deep research candidates, wiki/paper
  queue, artifact browser, and meeting report links.
- Include the read-only "Idea Intake" panel with CLI prompt guidance and recent
  raw/triaged ideas.
- Include a "Deep Research Decisions" panel that lists `needs_deep_research`
  ideas and shows the explicit command
  `vibe deep-request-from-idea <idea_id>`.
- Keep default dashboard read-only.

### Dashboard Server

- Add `vibe dashboard serve`.
- Serve local static files on configured host/port.
- Do not assume cloudflared or public writable access.
- Codex quota display must be `unknown/manual` unless backed by explicit local
  state.

### Meeting Export

- Add `vibe export-meeting [--date YYYYMMDD]`.
- Output `.vibe/reports/meeting/YYYYMMDD/`.
- Generate:
  - `story.md`
  - `timeline.md`
  - `leaderboard.md`
  - `key_runs.md`
  - `idea_pool.md`
  - `deep_research_status.md`
  - `paper_summary.md`
  - `evidence_table.csv`
  - `slides_outline.md`
  - `figures/`
- Do not generate manuscript or formal PPT.

### Final Reports and Portal Docs

- Generate `.vibe/reports/dev/alignment_after_changes.md`.
- Generate `.vibe/reports/dev/test_summary.md`.
- Generate `.vibe/portal/INSTALL.md`.
- Generate `.vibe/portal/USAGE.md`.
- Generate `.vibe/portal/AGENTS_SNIPPET.md`.

### Dogfood

- Run a cheap local/mock cycle only.
- Validate init, config, idea pool, plan-cycle, portfolio review, mock run,
  collect, reflect, revised plan, cycle revised plan, dashboard,
  deep-request-from-idea, and meeting export.

### 0.6.0 Tests

- Synthetic dashboard build.
- Dashboard serve local static smoke test.
- Meeting export story pack.
- Revised-plan invariant.
- Cycle revised-plan invariant.
- CLI smoke test for all new commands.

## Versioning and Commits

- Commit after each version stage:
  - `feat: add config and portal alignment`
  - `feat: add project brief idea pool and deep research from idea`
  - `feat: add dashboard meeting export and dogfood reports`
- Bump versions:
  - `0.4.0` after audit/config/portal work.
  - `0.5.0` after idea/deep research from idea work.
  - `0.6.0` after dashboard/meeting/dogfood work.
- Keep `pyproject.toml` and `vibe_research/__init__.py` in sync.
- Before every commit, update `CHANGELOG.md`.

## Final Acceptance

- `env_vibe_research/bin/python -m pytest -q` passes.
- `vibe init --minimal --no-root-portal` creates only `.vibe/`.
- `vibe portal build` can recreate root mirrors.
- `vibe config validate` passes on generated config.
- Fake Slurm config detect writes `.vibe/config.detected.yaml`.
- Normal init requires or imports project goal/background.
- Optional init ideas are captured into raw inbox and idea pool.
- Idea pool lifecycle works and appears in dashboard.
- `vibe deep-request-from-idea idea_XXX` creates a contextual request.
- Markdown/PDF deep research ingest updates wiki and idea pool.
- Static dashboard builds to `.vibe/site/index.html`.
- `vibe export-meeting` creates the story pack.
- Reports and usage docs exist under `.vibe/reports/dev/` and `.vibe/portal/`.
