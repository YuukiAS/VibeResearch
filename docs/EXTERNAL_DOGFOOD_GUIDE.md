# External Dogfood And Legacy Archive Guide

External dogfood validates VibeResearch against a real downstream repository
without hardcoding that repository into the framework.

Recommended flow:

```bash
vibe bootstrap dogfood --external-repo /path/to/repo --brief-file /path/to/problem.md --dry-run --output-report /tmp/dogfood.json
vibe bootstrap archive --source /path/to/repo --note "legacy automation before fresh bootstrap"
```

For a full rebootstrap, preserve old automation first. Do not delete old
evidence:

1. Record the old repo path and old automation directories.
2. Archive or rename old `.vibe/`, dashboards, timelines, leaderboards, run
   metadata, results, and failure notes.
3. Initialize a fresh `.vibe/` with the current VibeResearch.
4. Run `vibe bootstrap run`.
5. Answer blocker questions in the downstream repo.
6. Run contract tests and activate the minimum safe capability.
7. Generate readiness report and daily memo.
8. Classify dogfood findings as framework, adapter onboarding, script
   bootstrap, policy, external repo, or environment issues.

Old results import as untrusted historical context:

```bash
vibe bootstrap import-legacy .vibe/archives/<archive_id>/manifest.json
```

Imported legacy records default to `imported_unverified`. They must not support
promotion unless current adapter revision, capability id, metrics schema,
artifact rules, and provenance validate them.
