# VibeResearch Bootstrap Guide

This guide shows the v0.8.1 onboarding flow for a fresh or clean downstream
repository.

## End-To-End Flow

```bash
vibe init --goal "..." --background "..."
vibe bootstrap init --goal "..." --background "..." --memo-language zh-CN
vibe bootstrap run
vibe bootstrap status
vibe bootstrap doctor
```

Bootstrap phases are ordered and resumable:

1. `intake`: read README, AGENTS.md, briefs, existing `.vibe/`, adapter,
   policies, and historical result hints.
2. `discovery`: scan scripts, configs, tests, Slurm files, notebooks, metrics,
   logs, leaderboards, and environment files.
3. `draft`: generate adapter, script bootstrap plan, policy drafts, memo
   config, and research registry initialization.
4. `questions`: write blocker and non-blocker questions.
5. `validation`: run adapter lint, contract tests, and policy completeness
   checks.
6. `activation`: activate only capabilities with passed contract tests.
7. `report`: write readiness reports, dashboard exports, and daily memo.

If a phase blocks, fix the generated files or answer the questions, then run:

```bash
vibe bootstrap resume
```

Resume detects changed README, AGENTS.md, adapter, script, question, and policy
files. It preserves user edits and records merge warnings instead of silently
overwriting confirmed choices.

## Outputs

- `.vibe/bootstrap/state.json`
- `.vibe/bootstrap/latest.json`
- `.vibe/bootstrap/sessions/<session_id>.json`
- `.vibe/bootstrap/readiness_report.md`
- `.vibe/bootstrap/readiness.json`
- `.vibe/script_readiness.json`
- `.vibe/dashboard/readiness_export.json`
- `.vibe/memos/YYYY-MM-DD.md`

Readiness is not pass/fail. It states which capabilities are active, which
policies are incomplete, which scripts are untrusted, which contract tests
failed, and what the smallest actionable next step is.
