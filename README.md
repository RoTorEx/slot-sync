# SlotSync

Python CLI and scheduled automation for Google Calendar busy-time copies.
The production routes are Aveni and Thira into the explicit Innowise primary.
Source calendars remain read-only. There is no web server or Docker requirement.

This repository preserves Gallendar's history, TOML routes, OAuth credential
format and managed-event identities. Python is a fresh implementation; the
Rust runtime and original local checkout were removed after migration acceptance.
Legacy config paths and event markers remain compatible. Current calendar behavior is
specified in [BUSINESS.md](BUSINESS.md), server procedures in
[deploy/README.md](deploy/README.md), and observed verification in
[business/python-migration.md](business/python-migration.md).

[Privacy information](PRIVACY.md) explains data access, storage and removal.
Google setup and public app information are described in
[Google publication](business/google-publication.md).

## Development

Python 3.11 or newer and uv are required for packaging. The OAuth sync path uses
the standard library; the locked Google Auth dependency supports service-account
keys. The distribution is a portable Python wheel, not a bundled interpreter.

```sh
make install
uv run slot-sync --help
uv run slot-sync demo --json
make check
make package-release
```

The project lives under `personal/tools/slot-sync`. Release packages
are built under `~/construction_side/slot-sync/dist` by default.

## Configuration and commands

```sh
slot-sync setup --no-edit
slot-sync config --edit
slot-sync auth login --account aveni
slot-sync auth status --json
slot-sync doctor --json
slot-sync preview --details --json
slot-sync sync --apply --json
slot-sync status --json
```

With no command, the CLI displays help. `sync` previews unless `--apply` is
explicit. `preview` always previews. Options `--config`, `--state` and `--json`
work before or after the command. `init` and `setup-config` alias `setup`.
`config --edit` uses VISUAL, EDITOR or vi as a single executable, without shell
interpolation. Setup preserves an existing config.

The default config is `~/.toolbelt/slot-sync/config.toml`; its directory
can be changed with SLOT_SYNC_HOME. SLOT_SYNC_CONFIG and the
legacy GALLENDAR_CONFIG are supported. OAuth and service-key paths are resolved
relative to the config file. The bundled example documents existing TOML fields.
Production uses the existing explicit server config path rather than moving
credentials during the runtime change. A private byte-for-byte import can be
kept in `.local/gallendar-import/config.toml`, with its relative `secrets` path
linked to the existing protected credential store on that machine. `.local/`
is ignored by Git. The import is not a new route configuration; validate it with
the Python parser before changing any service entry point. Keep server config
and credentials outside the installed release so replacing code preserves them.

`calendar ensure --account NAME` explicitly creates a named secondary calendar
if configured and absent. Normal synchronization never creates calendars.
`availability --account NAME --start RFC3339 --end RFC3339` compares primary,
source and clone intervals; API results do not prove colleague UI behavior.

OAuth uses a loopback browser callback, PKCE, a random state and verified account
email. Each account has its own 0600 token file under a 0700 token directory.
Refresh does not open a browser. Reauthorization and transient failures have
different health states. Sign in locally, then transfer only the intended token
over SSH while the server writer is stopped. Never revoke a token merely to
remove its local copy: the server may use the same refresh grant.

## Scheduling and persistence

On the VPS, systemd runs `slot-sync sync --apply --scheduled --json`.
The timer owns the schedule; the Python process exits after each pass. Current
production cadence is every 30 minutes, preserving the previous schedule.
Change both the timer and poll_seconds together when changing cadence: the
health monitor derives its overdue threshold from poll_seconds.

SQLite contains durable creation IDs and pass outcomes. An uncertain insert
reuses its saved ID; a confirmed deleted event receives a new ID for recreation.
Remote legacy ownership markers remain authoritative for adopting existing copies.
The application does not identify duplicates by title or time alone. Detailed
plans and per-operation audit entries stay in private daily JSONL logs. Audit
failure stops before further writes. No event titles or credentials appear in
public health snapshots.

Applied passes acquire both the legacy config lock and the SQLite state's lock.
All jobs must use the same state path. A preview reads without an apply lock,
never creates state and never advances health. Locks are local to the host;
multiple independent writable servers are unsupported. Only the VPS runs writes.

SLOT_SYNC_STATE, SLOT_SYNC_LOGS and SLOT_SYNC_HEALTH_DIR
select persistent paths. GALLENDAR_HEALTH_DIR remains accepted during migration.
Only `--scheduled` applied passes publish schema-v1 health. Foreground `run`
remains available for manual operation, aligns passes to poll_seconds boundaries
and handles SIGINT/SIGTERM. Do not run it alongside the system timer.

`daemon start|stop|restart|status` controls the installed Linux timer. Systemd
administration permissions are required; stopping also stops an active pass.
No macOS launch agent is installed by the Python project.

The legacy `auto_update` field is accepted for config compatibility, but code
updates are deliberately performed by deployment, never by the running sync.
The old Rust self-updater and macOS daemon installer are replaced by the Python
package and server timer. CLI `update` is not provided. This operational change
keeps rollback and dependencies explicit.

## Release

The initial Python patch continues the upstream 0.2.x version line. Use the
interactive `make release`, enter the exact version at its prompt, then run
`make release-push`. Only the current Python tag is pushed; inherited Gallendar
tags are retained locally without publishing old Rust releases in this repository.
CI checks Linux and macOS, builds the wheel/source archive, installs the wheel
in a clean environment, and publishes checksummed assets for release tags.
No PyPI publication is configured.

## Personal Toolbelt installation

Keep the installed runtime separate from this source checkout. Build the wheel
with `make package-release`, retain the selected wheel under
`~/.toolbelt/slot-sync/packages/`, then install it using:

```sh
UV_TOOL_DIR="$HOME/.toolbelt/slot-sync/runtime" \
UV_TOOL_BIN_DIR="$HOME/.toolbelt/slot-sync/bin" \
uv tool install --force --from /absolute/path/to/retained-wheel.whl slot-sync
```

The executable is `~/.toolbelt/slot-sync/bin/slot-sync`; configuration remains
`~/.toolbelt/slot-sync/config.toml`. Replacing a wheel never authorizes a calendar
synchronization. Use the same Toolbelt directories for subsequent package updates.
