# SlotSync privacy information

SlotSync is a self-hosted calendar automation for its operator and their
connected accounts. It is not a hosted service that collects calendars from the
public. The operator controls where the software runs and which calendars are
connected.

## Access and use

With the account owner's permission, the application reads calendar event IDs,
titles, times, recurrence information, busy/free state and attendee responses
needed to determine the owner's availability. It uses the signed-in email address
to verify that credentials belong to the intended configured account.

Configured destinations receive busy-time copies. Depending on the selected
route, a copy contains the original title or a generic title, an optional prefix,
and its occupied interval. Configured additional guests can receive invitations,
updates and cancellations. Source descriptions, locations, conference links,
attachments and source guest lists are not copied.

Copies remain subject to the destination calendar's sharing settings and the
configured event visibility. In visible-title mode, people with appropriate
calendar access can see the copied title. The operator must select accounts,
destinations, visibility and guests that are appropriate for their data.

## Storage and sharing

OAuth credentials are stored on the operator's machine or server in protected
files. Local persistent state stores event identities and synchronization pass
records. Private audit logs can contain planned copy titles, times, calendar
identifiers and configured guest addresses. These records are not uploaded to
this public source repository by the application.

The application communicates with Google to authenticate and synchronize the
configured calendars. An optional operator-configured monitor receives health
status without event titles, event contents or credentials. Calendar contents
are not sent to advertising, analytics or AI services by this application.
The application does not sell Google user data.

Use and transfer of information received from Google APIs adhere to the
[Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy),
including its Limited Use requirements.

## Retention and removal

Local credentials, state and audit logs remain under the operator's control
until removed. Disabling the scheduler stops future synchronization. The owner
can revoke the application's account access through
[Google Account connections](https://myaccount.google.com/connections).
Revoking access or uninstalling does not automatically delete already-created
calendar copies. The operator can remove those copies and local stored data
separately, while preserving unrelated original calendar events.

## Contact

The maintainer is available through the
[project repository](https://github.com/RoTorEx/slot-sync).
Do not post credentials, private calendar contents or account details in public
issues. This document describes this application's behavior; the operator's
hosting provider and Google have their own applicable privacy policies.
