# SlotSync product rules

## Purpose and scope

A personal scheduled automation that reflects Aveni and Thira busy intervals
into the explicit Innowise primary calendar. The user needs colleagues and
booking tools to see occupied time. A secondary-calendar experiment failed that
real scheduling check; do not move copies back to a secondary calendar to hide
visual duplicates. Dato's display filters exclude the configured source prefixes.

The Python migration imports the existing Gallendar configuration without changing
routes, prefixes, visibility, guest rules, all-day behavior, namespace or managed
copy identities. Account login and publication setup do not authorize adding a
calendar route, deleting existing copies or starting synchronization. Personal
account authentication does not make that calendar a synchronization source.

The Python migration preserves the current calendar behavior. Reverse editing,
personal calendars, additional providers, a web UI and multiple active writer
hosts remain deferred. Multi-directional route configuration is inherited, but
managed copies never become independent source events. This is directed busy
reflection, not bidirectional editing of shared meeting entities.

## Rules

- Routes select source and destination accounts. There are two to four accounts;
  all calendars use explicit IDs, with no source ID also used as a destination.
  Omitted routes retain legacy all-to-all behavior across separate copy calendars.
- Each eligible source occurrence yields one desired copy per routed target.
  Free events, cancelled events, birthdays, working locations and invitations
  declined by the configured owner are excluded. Other guests' declines do not
  suppress an event. Tentative busy events remain included.
- The operator explicitly chooses `busy` or `out_of_office_only` for all-day
  events. Source calendar time zones govern day boundaries, including DST.
  Ambiguous, nonexistent or malformed boundaries fail the pass before writes.
- A moved recurring occurrence keeps its identity through series ID and original
  start time. Each instance is reconciled independently within the rolling window.
- Visible mode preserves the title, including an empty one, and uses public
  visibility. Hidden mode uses the configured hidden title and private visibility.
  Legacy original mode retains default visibility. Prefixes are literal and
  apply in either mode. Existing future copies update without changing identity.
- Only selected title and times are copied. Descriptions, locations, meeting
  links, attachments, recurrence definitions and source guest lists are excluded.
  Copies are opaque, confirmed default-type events without default reminders.
- Only explicit route attendees receive invitations. They cannot be configured
  accounts, preventing invitation feedback. Existing RSVP responses survive
  updates. Guest additions, removals and cancellations use notification-aware API
  operations; source attendees are never edited.
- Every source, target and retired target is read fully before a plan is applied.
  Incomplete pages, read failures or insufficient roles produce no writes.
  Retired targets allow only owned-copy cleanup after active targets are filled.
- Ownership requires the unchanged legacy gallendar=v1 marker and hashed namespace.
  Logical keys use the original length-prefixed UTF-8 SHA-256 format. Foreign
  events and past managed copies are preserved. Future duplicate managed keys,
  orphaned copies and future copies outside the horizon are reconciled.
- Updates and deletions recheck ownership, require ETags, and verify remote
  state after writing. Sensitive-field pollution is repaired by replacement.
  A pass can partially apply if a later write fails; the next pass reconciles it.
- SQLite records a creation identity before insertion. Lost responses retry the
  same ID, while confirmed deleted events receive a fresh ID. SQLite is local
  durable state, not a transaction spanning Google and the local disk.

## Operating contract

Only one VPS writes the production namespace. Local config and state locks
prevent overlapping cooperating processes on that host, including the old Rust
config lock during migration. Random schedule offsets do not establish mutual
exclusion across machines. Google credentials and public health are separate.

The existing horizon is 14 days and polling interval 1800 seconds. The accepted
horizon range is one to thirty days; the current interval keeps source changes
within the next half-hour pass, subject to API availability and pass duration.
Systemd owns scheduling and boot activation. A stopped old writer remains
available for explicit rollback; the Mac daemon stays absent.

The health schema remains version 1 for Telegram Assistant compatibility.
Successful scheduled passes advance last_success_at; failed passes preserve it.
Explicit reauthorization is distinct from generic sync failure. Existing monitor
thresholds remain owned by Telegram Assistant: immediate reauthorization/missing
state detection, and overdue after two polling intervals. A complete VPS outage
requires monitoring outside that VPS.

Implementation: config.py validates contracts; model.py owns identities/privacy;
planner.py computes changes; google.py and oauth.py own provider boundaries;
runner.py, storage.py and health.py own execution/recovery/monitoring.
Historical checks: [validation.md](business/validation.md). Python migration
checks and limits: [python-migration.md](business/python-migration.md).
