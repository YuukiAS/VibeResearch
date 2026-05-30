# Policy Completeness And Script Hardening

v0.8.1 adds readiness checks that prevent project bootstrap from becoming fake
execution.

Policy completeness rules:

- Missing budget policy blocks queue submission.
- Missing autonomy policy blocks automatic execution.
- Missing stage-gate policy blocks promotion.
- Missing memo config warns but does not block low-risk initialization.
- Missing protected metrics blocks automatic higher-stage promotion.

Script readiness is exported to `.vibe/script_readiness.json`. Generated
wrappers remain draft or untrusted until contract tests prove they perform a
real interface action, such as parsing a config, checking an input path,
calling a project entrypoint, generating sample metrics, or validating an
artifact.

Placeholder wrappers, string-only commands, missing expected outputs, and
schema-invalid sample metrics cannot become active capabilities.
