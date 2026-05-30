# Local Dogfood Sandbox Guide

v0.8.1 supports ignored local bootstrap sandboxes under `.vibe_dogfood/`.
These sandboxes are for development dogfood and should not be committed.

`.gitignore` includes:

```gitignore
.vibe_dogfood/
```

Create or run profiles:

```bash
vibe bootstrap sandbox --profile 0.8.1-happy-path
vibe bootstrap dogfood --profile 0.8.1-happy-path
vibe bootstrap dogfood --profile 0.8.1-missing-metrics
vibe bootstrap dogfood --profile 0.8.1-policy-conflict
vibe bootstrap dogfood --profile 0.8.1-placeholder-script
vibe bootstrap dogfood --profile 0.8.1-resume-after-failure
```

The happy path includes README, AGENTS.md, a minimal evaluation script, sample
metrics, and bootstrap answers so one low-risk evaluation capability can become
active. Broken profiles verify that missing metrics, policy conflicts,
placeholder wrappers, and interrupted initialization become state, questions,
and readiness report blockers rather than fake progress.
