# Python migration acceptance

The accepted task is a local copy under personal/automations/callendars-syncer,
a fresh Python implementation of current busy-copy behavior, project navigation
registration, a public GitHub repository, a patch release and verified replacement
of the current VPS writer. The user explicitly selected cutover after checks.

The original checkout and its production binary remain rollback sources. No new
reverse-editing routes or artificial events are authorized as part of the rewrite.

## Required evidence

- Focused offline contract tests, package installation and Linux/macOS CI.
- Live doctor and agreement of Python/Rust plans against unchanged source data.
- No unexpected calendar changes or guest notifications at cutover.
- One writer only, successful Python applied passes, durable SQLite state and
  fresh schema-v1 health visible through the existing bot mount.
- Disabled old writer, timer activation, stable copy identities and rollback path.

Observed results are recorded here after verification. Existing historical
colleague observations remain in validation.md; they are not new Python tests.
