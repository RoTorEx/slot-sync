# Python migration acceptance

The accepted task is a local copy under personal/automations/slot-sync,
a fresh Python implementation of current busy-copy behavior, project navigation
registration, a public GitHub repository, a patch release and verified replacement
of the current VPS writer. The user explicitly selected cutover after checks.

The initial cutover retained the Rust checkout and binary as temporary rollback
sources. After acceptance, the legacy local checkout, deployed Rust binary and
systemd unit were removed at the operator's request. Git history and private
configuration recovery material remain; no installed Rust rollback is available.
No new reverse-editing routes or artificial events are authorized by the rewrite.

## Required evidence

- Focused offline contract tests, package installation and Linux/macOS CI.
- Live doctor and agreement of Python/Rust plans against unchanged source data.
- No unexpected calendar changes or guest notifications at cutover.
- One writer only, successful Python applied passes, durable SQLite state and
  fresh schema-v1 health visible through the existing bot mount.
- Disabled old writer, timer activation, stable copy identities and rollback path.

Observed results are recorded here after verification. Existing historical
colleague observations remain in validation.md; they are not new Python tests.

## Offline verification

Thirty-six focused tests passed locally and on Debian. Non-release GitHub Actions
run 39428087719 passed Linux checks on Python 3.11/3.13, macOS checks on Python
3.14 and clean Python package installation. These establish the implementation
and delivery checks, not completed production migration. Private operational
observations are retained outside Git. Live server acceptance is recorded below.


## Live VPS acceptance (2026-10-21)

The inherited configuration was used with the replacement OAuth client and token
store. Route direction, prefixes, visibility, guest rules, namespace and all-day
policy were preserved. A server-side horizon reduction to one day removed only
owned future destination copies outside the desired window; returning to fourteen
days recreated the missing copies. Destination read-back matched the full desired
logical-key set with no duplicates. Past managed events and unrelated destination
events matched their pre-change snapshots. Source calendars were read only.

The published 0.2.9 wheel was installed in its versioned VPS environment after
checksum and package smoke checks. Its systemd installer repaired private runtime
directory ownership. The old writer was stopped, disabled and inhibited; the
Python timer is enabled at the inherited thirty-minute cadence. Two subsequent
applied server passes reported no changes, with successful SQLite pass records
and fresh schema-v1 health for the installed version at the original health path.

These observations establish API reconciliation, restart idempotence and server
scheduling. They do not constitute a new colleague booking-UI check or a fresh
end-to-end bot check. The Mac did not run live synchronization. Network settings,
the bot and metrics were not changed. Detailed snapshots and recovery materials
remain private on the VPS rather than in this public repository.


## Legacy runtime retirement (2026-10-21)

Following successful Python acceptance, the old VPS unit, dedicated cutover
drop-in, restart marker and Rust executables were removed. The old local checkout
and installation remnants were also removed after verifying that its committed
history is an ancestor of SlotSync. SlotSync has no Git alternates dependency on
the deleted checkout, and its obsolete local source remote was removed.

The canonical compatibility config path, active OAuth credentials, SQLite state,
private recovery data and existing health path remain in place. The retained
legacy path and Unix service-user names are data compatibility details rather
than an installed Gallendar application. A prior compatible Python version is
the supported rollback target.
