# VibeResearch

VibeResearch is a repo-specific sustained research orchestration framework.
Run `vibe init` inside a target repository to create a `.vibe/` control layer,
root-level progress files, and a deterministic runner/scheduler boundary.

The framework intentionally separates LLM-generated planning artifacts from
trusted execution state. Codex can write plans, reviews, manifests, patches,
reflections, and revised plans; local Python commands own dry-runs, Slurm
submission, monitoring, collection, provenance, dashboards, and merge records.

```bash
python -m vibe_research.cli init --target /path/to/repo
python -m vibe_research.cli status --target /path/to/repo
python -m vibe_research.cli next --target /path/to/repo
```

