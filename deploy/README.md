# Python deployment and Gallendar replacement

The intended target is the existing Linux VPS. Retain the gallendar service user,
config, token files, namespace and safe health path so the Telegram bot requires
no mount or configuration change. Python is installed in an isolated versioned
virtual environment; no system Python packages are overwritten.

## Paths

- Code: `/opt/slot-sync/releases/VERSION/venv`.
- Active release link: `/opt/slot-sync/current`.
- Existing config: `/srv/gallendar/.x-cli-gallendar/config.toml`.
- Existing OAuth files: paths relative to that config, unchanged.
- New private state: `/srv/gallendar/slot-sync/state.sqlite3`.
- New private logs: `/srv/gallendar/slot-sync/logs`.
- Existing public health: `/srv/gallendar/health/health.json`.

A release must include the wheel and SHA-256, matching units, and locked Python
requirements. Install with pip in a private release environment using the exported
hashed lock, then install the wheel with --no-deps. Read back the installed
version, run the offline demo and tests, then live doctor and preview. Credentials
must remain readable only by the intended service identity. Release code is
root-owned and the service cannot modify it.

## Cutover

1. Keep the old writer running while installing and doing read-only validation.
   The Python preview may refresh OAuth, but does not write calendar events.
2. Compare its plan with Rust using the same config and a read-only comparison
   copy in the same private directory if needed to avoid Rust's held config lock.
   Investigate any unexpected create, update, delete or logical-key difference.
3. Preserve the old unit, executable identity, private config/OAuth snapshot and
   the current health snapshot under a root-only recovery directory.
4. Install both new units with `scripts/install-systemd.sh`; it does not start them.
   The installer also creates or repairs the runtime and log directories with
   owner/group gallendar and mode 0700. A root-owned runtime directory otherwise
   prevents the service from opening SQLite or recording its first pass.
5. Stop and disable `gallendar.service`; verify MainPID=0. Inhibit the old unit with
   a drop-in condition so accidental starts cannot race with the Python timer.
6. Set `/opt/slot-sync/current` to the verified release. Run
   `systemctl start slot-sync.service`. Verify its successful exit,
   fresh health, private pass counts and another no-change preview.
7. Enable `slot-sync.timer` with --now and read back the next activation.
   Re-run the oneshot service to verify restart/recovery and no extra copies.
8. Read the health snapshot through the bot's actual mounted path. Do not
   fabricate production reauthentication failures for a monitoring check.

The timer runs every half hour. `Persistent=true` catches missed activation on
restart. It does not create concurrent instances of the same service. The service
also conflicts with the retired Gallendar unit and takes its legacy config lock.
Those protections are host-local; do not deploy another active writer server.

## Rollback

Stop and disable slot-sync.timer, then stop slot-sync.service and
verify no Python writer remains. Remove the old service's migration condition
from its dedicated drop-in, reload systemd, then enable/start gallendar.service.
Keep the existing config and latest OAuth files: do not overwrite rotated refresh
tokens with older recovery copies unless repairing confirmed corruption. The
original binary, event markers and namespace remain compatible. Check a successful
old-engine pass and the bot's health view. Preserve the Python SQLite state for
investigation or a later return.

## Reauthorization and updates

Stop the timer and active pass before replacing a credential. Sign in locally
using the existing Desktop OAuth client and intended account, transfer only that
account file atomically with owner gallendar and mode 0600, run doctor, then start
the service and timer. Token directories remain 0700. Production OAuth Audience
status is a separate operator check; working refresh does not establish it.

Update by staging a new versioned environment and doing the same doctor/preview
checks, stopping the timer/pass, moving the active link, starting and verifying.
Code never self-updates. Back up SQLite using its online backup API or while the
writer is stopped, alongside configuration and appropriately protected secrets.
