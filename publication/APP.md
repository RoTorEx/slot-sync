# SlotSync

SlotSync is a self-hosted command-line application that reflects calendar busy
time between Google accounts selected by its operator. It runs on the operator's
computer or server and uses Google Calendar API with explicit account consent.

The operator configures directed routes, destination calendars, title visibility
and optional prefixes. Source calendars remain read-only. Destination copies
contain the selected title and occupied interval; source descriptions, locations,
conference links, attachments and source guest lists are not copied. Hidden-title
mode remains available. Managed copies preserve stable identities across passes.

This is personal automation, not a public hosted calendar service. It does not
sell Google user data or send calendar contents to advertising, analytics or AI
services. The operator controls credentials, local state, audit logs and removal.
See PRIVACY.md in this Gist for the complete privacy information.

Source and releases: https://github.com/RoTorEx/slot-sync
Maintainer: https://github.com/RoTorEx

Google OAuth Production status and Google verification are separate. This
publication does not claim that Google has verified the application. A public
Gist documents the app; it is not proof of DNS-level domain ownership.
