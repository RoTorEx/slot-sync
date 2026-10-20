# Google setup and publication

The Google Cloud project, service identity, OAuth Desktop client and individual
account grants are separate objects. A service-account key is not an OAuth client
JSON and does not replace user consent or corporate calendar sharing permission.
A project name or service-account name change must preserve the active calendar
configuration and existing credentials unless a separate migration is authorized.

## Public information

The public app description is owned by [APP.md](../publication/APP.md), and the
privacy policy by [PRIVACY.md](../PRIVACY.md). Their derived public Gist is:
https://gist.github.com/RoTorEx/826a0ea78488ab3d2fe3023bfe6e14b3

Update the repository source before updating the Gist. Publish only the app
information and privacy text, never private configuration, credentials, calendar
contents or operator recovery details. Gist publication does not establish
DNS-level ownership of github.com or imply Google approval.

## OAuth preparation

Prepare a Desktop client in the intended project, keep its JSON in a protected
credential directory and use separate token storage while validating a new client.
Declare the actual runtime scopes: openid, userinfo.email,
calendar.events.readonly, calendar.events and calendar.events.freebusy. Source
accounts request read-only event access; configured destinations request event
write access. Identity scopes verify the configured account. Declare any additional
scope only when required by an enabled feature and represented in the app behavior.

Audience Production and completed Google verification are different states.
Production avoids the Testing-specific seven-day refresh-token limit; revocation,
expiry and organization policy can still require another sign-in. Personal-use
exceptions can permit operation with the unverified-app screen and user cap.
See [Google verification exceptions](https://developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification#exceptions-to-verification-requirements).

A complete verification request requires compliant branding, a suitable homepage
and privacy policy, domain ownership, actual scope justification and a demonstration
of the requested access. Google currently documents DNS-level Domain Property
verification rather than URL-prefix verification for OAuth domain ownership:
https://support.google.com/cloud/answer/13804266
A Gist, LinkedIn profile or HTML-only Pages verification does not satisfy that
stated DNS requirement. Do not mark the application verified before Google approves.

## Login-only boundary

Account login does not authorize synchronization. Inherit Gallendar's route and
privacy settings unchanged. Do not add personal-calendar routes or reconcile
existing copies while preparing identity grants. Never switch from existing OAuth
to a service-account key merely because a new service identity was created.

## Credentials and access checks

Keep new-client credentials and tokens separate from the active client's store
until its account grants have been verified. Login-only configuration may change
OAuth client and token paths; all inherited route and event-behavior fields must
remain identical. Verify the new grant's owner, client and required scopes, refresh
it, then read the configured calendar role at the intended runtime destination.
None of these checks requires writing an event or starting synchronization.

A service identity is connected to a calendar through that calendar's sharing
settings, not by signing into a service-account mailbox. Use the explicit calendar
ID for checks; shared calendars do not necessarily appear in CalendarList. Read
sources require event-detail access; destination writes require a writer role.
Workspace policy can cap externally granted access at free/busy. Preserve OAuth
for destinations with invited guests unless the required domain-wide delegation
has separately been authorized and implemented. See Google's
[calendar sharing](https://developers.google.com/workspace/calendar/api/concepts/sharing)
and [event attendee requirements](https://developers.google.com/workspace/calendar/api/v3/reference/events).

For browser diagnostics, output only allow-listed non-secret controls and safe
status fields. Credential values can appear in accessible copy-button names;
OAuth callback parameters can appear in browser tab titles. Do not dump credential
dialogs, copy-button labels or callback URLs. Download JSON directly to the
protected store, verify project/client metadata without printing secret values,
and remove the task-owned download copy. If an unused credential is exposed,
revoke and replace that credential before use, with authoritative read-back.
