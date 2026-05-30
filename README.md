<h1 align="center">VibeResearch</h1>
<h3 align="center">A repository-local control layer for sustained research workflows</h3>

<p align="center">
  <strong>VibeResearch keeps planning, execution state, evidence, and reports inside each target repository's <code>.vibe/</code> directory.</strong>
</p>

<p align="center">
  <a href="README.md">English</a> |
  <a href="docs/README_CN.md">中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python"/>
  <img src="https://img.shields.io/badge/state-.vibe%2F-informational.svg" alt=".vibe state"/>
  <img src="https://img.shields.io/badge/dashboard-read--only-lightgrey.svg" alt="Read-only dashboard"/>
</p>

---

## Overview

VibeResearch is a local-first framework for managing long-running research work
inside an existing code repository. It creates a `.vibe/` workspace in the
target repo and uses that workspace as the authoritative store for project
context, ideas, plans, run metadata, scheduler state, evidence, dashboards, and
daily notes.

The framework separates reasoning from execution. A human or coding agent can
write plans, reviews, hypotheses, and analysis notes. VibeResearch records the
state, validates contracts, schedules runs, tracks provenance, collects
metrics, and blocks unsafe automation when required information is missing.

Typical use cases include:

- keeping iterative research work reproducible across many cycles;
- connecting a project-specific training or evaluation script to a generic
  orchestration layer;
- running local or Slurm-backed experiments with explicit budget and readiness
  gates;
- preserving old failed attempts as historical evidence without trusting them
  automatically;
- producing status dashboards, daily memos, and meeting-ready summaries.

## Installation

Install from a clone of this repository:

```bash
git clone https://github.com/YuukiAS/VibeResearch.git
cd VibeResearch
python -m pip install -e .
```

Check that the command line interface is available:

```bash
vibe --help
vibe bootstrap --help
```

## Quick Start

Initialize a target research repository:

```bash
cd /path/to/research-repo
vibe init \
  --goal "Improve validation performance under a fixed evaluation protocol" \
  --background "Project context, data, metrics, compute limits, and current baseline"
```

Inspect the state:

```bash
vibe config validate
vibe status
vibe next
```

If the target repository should not receive generated root-level mirror files,
use:

```bash
vibe init --no-root-portal --goal "..." --background "..."
```

## Agent-Assisted Onboarding

For a new downstream repository, you can let Codex perform the installation and
bootstrap loop instead of following this README manually. Give Codex the prompt
in:

```text
docs/bootstrap/CODEX_ONBOARDING_PROMPT_CN.md
```

That prompt instructs Codex to clone VibeResearch from GitHub, install it, ask
for the required project goal and background, run bootstrap, summarize blockers,
write your answers into the target repository's `.vibe/` files, and resume the
initialization until a safe minimum capability is ready or explicitly blocked.

## Repository State Layout

VibeResearch keeps durable state under `.vibe/`:

```text
.vibe/
  project/                 project brief and initialization context
  config.yaml              framework configuration
  adapter.yaml             project capability contract
  adapter_questions.yaml   questions required before activation
  script_bootstrap_plan.md project wrapper plan
  scripts/                 project-owned wrapper scripts
  contract_tests/          adapter contract-test results
  policies/                budget, stage-gate, and autonomy policy
  state/                   scheduler and control state
  cycles/                  cycle-level plans and decisions
  runs/                    run manifests and provenance
  scheduler/               queue and budget state
  ideas/                   maintained idea pool
  research/                hypotheses, experiments, evidence, decisions
  memos/                   daily research notes
  dashboard/               machine-readable dashboard exports
  site/                    generated static dashboard
  reports/                 meeting and development reports
  portal/                  source for root-level generated mirrors
```

Root files such as `RUN.md`, `VIBE_STATUS.md`, `VIBE_TODO.md`,
`VIBE_TIMELINE.md`, and `VIBE_LEADERBOARD.md` are generated mirrors. The source
of truth remains under `.vibe/`.

Rebuild the mirrors with:

```bash
vibe portal build
```

VibeResearch does not modify a root `AGENTS.md` unless you ask it to:

```bash
vibe init --install-agents-snippet --goal "..." --background "..."
```

## Bootstrap And Readiness

The bootstrap workflow connects an existing project to VibeResearch in stages.
It discovers project files, drafts an adapter and wrapper plan, writes policy
files, records unanswered questions, runs validation, and activates only
capabilities that pass contract tests.

```bash
vibe bootstrap init --goal "..." --background "..." --memo-language zh-CN
vibe bootstrap run
vibe bootstrap status
vibe bootstrap doctor
```

If bootstrap stops on missing information, answer or edit the generated files
under `.vibe/`, then resume:

```bash
vibe bootstrap resume
```

Important outputs:

```text
.vibe/bootstrap/state.json
.vibe/bootstrap/sessions/<session_id>.json
.vibe/bootstrap/readiness_report.md
.vibe/bootstrap/readiness.json
.vibe/script_readiness.json
.vibe/dashboard/readiness_export.json
```

Readiness is intentionally conservative. Missing budget policy blocks queue
submission; missing autonomy policy blocks automatic execution; missing
stage-gate policy blocks promotion; missing protected metrics blocks automatic
higher-stage promotion.

Bootstrap and adapter discovery use a bounded file walker. Runtime-heavy
directories such as `.git/`, `.vibe/`, `.vibe_dogfood/`, `data/`, `results/`,
`models/`, `logs/`, `envs/`, and `external_supervisors/` are pruned before
descent. Project-specific limits can be set in `.vibe/config.yaml`:

```yaml
discovery:
  skip_dirs: [scratch, downloads]
  max_files: 200
  max_dirs: 1000
  max_seconds: 5
```

## Adapter Onboarding

The adapter is a project-specific contract that declares what VibeResearch is
allowed to do. Execution scripts are thin wrappers owned by the downstream
repository. The main VibeResearch package does not contain project-specific
training, evaluation, or submission logic.

Common adapter commands:

```bash
vibe adapter discover
vibe adapter draft
vibe adapter ask
vibe script bootstrap --plan
vibe adapter lint
vibe adapter doctor
```

Only `active` capabilities can be selected for execution. Draft, candidate, or
blocked capabilities appear in reports but cannot run. A capability becomes
active only after its contract test passes:

```bash
vibe adapter contract-test metrics_export
vibe adapter activate metrics_export --confirm "reviewed by project owner"
```

Generated wrappers in `.vibe/scripts/` are draft and untrusted until reviewed or
replaced by the downstream project. A safe onboarding sequence usually activates
evaluation or metrics export before any training or long-running job capability.

Instrumentation readiness is separate from real-experiment readiness. Probe
capabilities such as environment, data, and baseline inventory can verify the
project surface, but they do not count as method or evaluation experiments.
Use the real-experiment gap report to finish the project-specific contracts:

```bash
vibe adapter real-gaps
vibe experiment real-progress
```

## Bounded Research Management

The research manager tracks hypotheses, experiments, evidence, decisions,
budgets, and daily notes. It lets a project iterate over research ideas while
preserving the evidence chain that led to each decision.

```bash
vibe research init --goal "..." --background "..." --memo-language zh-CN
vibe hypothesis create "try a calibrated evaluator" --stage analysis
vibe experiment create hyp_001 --design "calibration smoke" --stage analysis --capability metrics_export
vibe experiment analyze exp_001 --trusted --schema-valid --summary "primary improved without guardrail regression"
vibe memory build
vibe portfolio plan
vibe portfolio schedule
vibe budget status
vibe memo daily --language zh-CN
vibe dashboard export-research
```

Promotion requires trusted, schema-valid evidence and no unacceptable protected
metric regression. Stopping requires trusted negative evidence or an explicit
user decision. Duplicate experiments, unknown cost, missing scripts, missing
metrics schemas, and unsupported capabilities are blocked before execution.

## Decision-To-Execution Safety

VibeResearch compiles structured decisions into resource plans before it creates
runs. This prevents free-form plan text from becoming executable work without
validation.

```text
revised_plan.md
  -> decision.json
  -> project adapter
  -> resource_plan.yaml
  -> run manifest
  -> trusted metrics only after schema and provenance checks
```

Useful commands:

```bash
vibe validate-decision c001
vibe decision show c001
vibe decision write c001 --type launch_gpu_gate --action "run configured adapter task"
vibe decision write-block c001 --reason "adapter missing"
vibe compile-decision c001
vibe validate-resource-plan c001
```

Repeated evidence-only loops and default or missing metrics are marked blocked
or untrusted. They do not update trusted leaderboard state.

## Ideas And Deep Research

The raw inbox captures user prompts. The maintained idea pool turns them into
stable research items:

```bash
vibe idea "compare two route-level approaches"
vibe ideas list
vibe ideas triage
vibe ideas promote idea_001
vibe ideas reject idea_001 --reason "out of scope"
vibe ideas archive idea_001
```

Deep research is explicit. Marking an idea as needing deeper investigation does
not automatically run research.

```bash
vibe deep-request-from-idea idea_001
vibe ingest-deep-research dr001_idea_001 --kind science
vibe ingest-deep-research dr001_idea_001 --kind workflow
vibe ingest-deep-research dr001_idea_001 --kind repo
vibe ingest-deep-research dr001_idea_001 --kind benchmark
```

Markdown and PDF reports are supported. PDF extraction uses PyMuPDF when
available; OCR is not attempted.

## Scheduler And Slurm

The scheduler is deterministic and budget-aware. It will not submit runs that
fail dry-run, have invalid manifests, violate dependencies, exceed budgets, or
are blocked by review.

Detect local settings:

```bash
vibe config detect
```

Cluster-specific configuration lives in:

```text
.vibe/config.yaml
.vibe/config.local.yaml
.vibe/scheduler/budget.yaml
```

Submit and monitor:

```bash
vibe submit-queue --backend slurm
vibe monitor --loop --auto-next
```

For local development:

```bash
vibe submit-queue --dry
```

## Dashboard And Reports

Build a static read-only dashboard:

```bash
vibe dashboard build
```

Serve it locally:

```bash
vibe dashboard serve --host 127.0.0.1 --port 8765
```

Export a meeting report package:

```bash
vibe export-meeting
vibe export-meeting --date 20260529
```

The export is written under:

```text
.vibe/reports/meeting/YYYYMMDD/
```

## Local Development

Run the test suite:

```bash
python -m pytest -q
```

The tests use offline Codex and dry scheduler paths. They do not require Codex
authentication, a GPU, a Slurm cluster, or network access.

For a packaged smoke workflow:

```bash
vibe dogfood
```

## Design Principles

- `.vibe/` is the authoritative state root.
- Root-level status files are generated mirrors.
- Project-specific execution logic stays in the downstream repository.
- Capabilities must be explicit, reviewed, and contract-tested before use.
- Long-running monitoring does not depend on language-model calls.
- Legacy results are historical context until validated under the current
  adapter, schema, artifact, and provenance rules.
