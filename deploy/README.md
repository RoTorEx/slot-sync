# Python deployment and Gallendar replacement

The intended target is the existing Linux VPS. Retain the gallendar service user,
config, token files, namespace and safe health path so the Telegram bot requires
no mount or configuration change. Python is installed in one isolated
virtual environment; no system Python packages are overwritten.

## Paths

- Single installed environment: `/opt/slot-sync/venv`.
- Installed package metadata records the version; Git/GitHub owns source history.
- Existing config: `/srv/gallendar/.x-cli-gallendar/config.toml`.
- Active OAuth client: `/srv/gallendar/slot-sync/secrets/oauth-client.json`.
- Active per-account OAuth tokens: `/srv/gallendar/slot-sync/secrets/oauth/`.
- Legacy credential files remain separate recovery material; production uses the
  newly verified grants through the OAuth paths in the inherited config.
- New private state: `/srv/gallendar/slot-sync/state.sqlite3`.
- New private logs: `/srv/gallendar/slot-sync/logs`.
- Existing public health: `/srv/gallendar/health/health.json`.

A release must include the wheel and SHA-256, matching units, and locked Python
requirements. Install with pip in the private installed environment using the exported
hashed lock, then install the wheel with --no-deps. Read back the installed
version, run the offline demo and tests, then live doctor and preview. Credentials
must remain readable only by the intended service identity. Release code is
root-owned and the service cannot modify it.

## Active production and updates

The legacy Gallendar executable and systemd unit have been uninstalled after
Python acceptance. The Unix identity and compatibility config/lock path remain
because active data and health consumers use them. Do not delete those paths as
part of application cleanup. The original local Rust checkout is also retired.

1. Verify a published Python wheel, checksum and locked dependencies in temporary staging.
   Validate its installed version and package smoke behavior, then doctor/preview
   against the intended private configuration. Source calendars stay read-only.
2. Preserve configuration, current OAuth credentials, health and an SQLite backup.
3. Stop slot-sync.timer and the active pass; verify no writer remains.
4. Install units with `scripts/install-systemd.sh`. It also creates or repairs
   runtime and log directories with owner/group gallendar and mode 0700. It does
   not start the timer or service.
5. Install into `/opt/slot-sync/venv` and start
   slot-sync.service. Read back a successful exit, fresh health and a no-change
   preview for stable source data.
6. Enable slot-sync.timer with --now and verify its next activation. A subsequent
   oneshot pass must reconcile without creating extra copies.

The timer runs every half hour. Persistent=true catches missed activation on
restart; systemd does not overlap instances of the same oneshot service. The
application additionally locks its canonical compatibility config and SQLite
state. All protections are local to this VPS; no second writer host is supported.

## Python rollback

Stop and disable slot-sync.timer, then stop slot-sync.service and verify no
writer remains. Reinstall an earlier published Python version into the same
`/opt/slot-sync/venv` that supports the current SQLite schema. Keep the current configuration and
latest OAuth files; do not overwrite rotated refresh tokens with stale recovery
copies. Start the service and check its successful pass and fresh health before
re-enabling the timer. Restoring the retired Rust application would be a separate
installation, not an existing service that can simply be restarted.

## Reauthorization and updates

Stop the timer and active pass before replacing a credential. Sign in locally
using the existing Desktop OAuth client and intended account, transfer only that
account file atomically with owner gallendar and mode 0600, run doctor, then start
the service and timer. Token directories remain 0700. Production OAuth Audience
status is a separate operator check; working refresh does not establish it.

Update by verifying a published wheel in temporary staging, stopping the
timer/pass, replacing the package in `/opt/slot-sync/venv`, then doing the same
doctor/preview checks, starting and verifying. Remove temporary staging and any
former release directories after success; keep one installed code copy.
Code never self-updates. Back up SQLite using its online backup API or while the
writer is stopped, alongside configuration and appropriately protected secrets.
