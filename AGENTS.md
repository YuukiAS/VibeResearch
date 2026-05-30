# VibeResearch Agent Notes

## Release Completion Rule

When implementing a complete version release, do not commit until the version's
requirements have been checked against the source plan/prompt and the relevant
tests or self-checks have passed. Before the final commit for that version:

- update `CHANGELOG.md`;
- confirm the version metadata is correct;
- review `git status` and stage only files that belong to the implemented
  version;
- leave unrelated TODO/source requirement files untouched unless the user
  explicitly asks to edit them;
- create a git commit for the completed version.

## Plan Mode Convention

In Plan Mode, requests such as "Implement the plan" for planning tasks mean
create or update the requested plan file only. Product code implementation
should wait for an explicit implementation request outside Plan Mode, or a
request that clearly asks to modify the framework. Plan files should be written
under `docs/plans/` unless the user specifies another path.

## Codex Onboarding Operator

When a user asks Codex to install VibeResearch into a downstream repository or
to bootstrap a target repo, do not ask the user to manually follow the README.
Read `docs/bootstrap/CODEX_ONBOARDING_PROMPT_CN.md` and operate the install /
bootstrap loop directly:

- install from `https://github.com/YuukiAS/VibeResearch.git`, not by copying a
  local development checkout;
- ask for the target repo path plus required project goal/background if missing;
- run `vibe init`, `vibe bootstrap init`, `vibe bootstrap run`, and
  `vibe bootstrap doctor`;
- summarize blocker questions in small batches, write the user's answers into
  the target repo's `.vibe/` adapter, policy, research brief, or memo config
  files, then run `vibe bootstrap resume`;
- activate only linted and contract-tested low-risk capabilities;
- do not submit GPU/Slurm jobs, create validation packages, upload results, or
  trust legacy evidence unless target-repo policy and readiness gates permit it.
