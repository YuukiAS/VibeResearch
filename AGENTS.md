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
