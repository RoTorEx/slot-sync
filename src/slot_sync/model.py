"""Stable legacy identities, privacy allowlists and timezone normalization."""
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from zoneinfo import ZoneInfo
from .config import SyncError, require

MANAGED, NAMESPACE, KEY = 'gallendar', 'gallendarNamespace', 'gallendarKey'


def digest(*parts):
    h = hashlib.sha256()
    for part in parts:
        b = part.encode('utf-8')
        h.update(len(b).to_bytes(8, 'big'))
        h.update(b)
    return h.hexdigest()


def instant(value):
    try:
        d = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(d.tzinfo is not None and d.utcoffset() is not None, 'Event dateTime needs an explicit UTC offset')
        return d.astimezone(timezone.utc)
    except (ValueError, TypeError, AttributeError):
        raise SyncError('Invalid event timestamp (value omitted)') from None


def normalize_time(value, calendar_zone):
    require(isinstance(value, dict) and bool(value.get('date')) != bool(value.get('dateTime')), 'Event needs exactly one of date or dateTime')
    if value.get('dateTime'):
        return {'dateTime': instant(value['dateTime']).isoformat()}
    try:
        naive = datetime.strptime(value['date'], '%Y-%m-%d')
        tz = ZoneInfo(value.get('timeZone') or calendar_zone)
        candidates = {naive.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc)
                      for fold in (0, 1)
                      if naive.replace(tzinfo=tz, fold=fold).astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == naive}
        require(len(candidates) == 1, 'Ambiguous or nonexistent all-day boundary')
        return {'dateTime': candidates.pop().isoformat()}
    except (ValueError, KeyError, TypeError):
        raise SyncError('Invalid all-day date or calendar time zone') from None


def private(event):
    return event.get('extendedProperties', {}).get('private', {})


def managed(event):
    return private(event).get(MANAGED) == 'v1'


def owned(event, namespace):
    return managed(event) and private(event).get(NAMESPACE) == namespace


@dataclass
class Busy:
    key: str
    start: dict
    end: dict
    summary: str = 'Busy'
    visibility: str = 'private'
    attendees: list = field(default_factory=list)

    def payload(self, event_id, namespace, current=None):
        p = {'id': event_id, 'summary': self.summary, 'status': 'confirmed',
             'eventType': 'default', 'visibility': self.visibility,
             'transparency': 'opaque', 'start': deepcopy(self.start), 'end': deepcopy(self.end),
             'reminders': {'useDefault': False},
             'extendedProperties': {'private': {MANAGED: 'v1', NAMESPACE: namespace, KEY: self.key}}}
        current = current or {}
        if self.attendees or current.get('attendees'):
            previous = {a.get('email', '').lower(): a for a in current.get('attendees', [])}
            p['attendees'] = []
            for email in self.attendees:
                guest = {'email': email}
                response = previous.get(email, {}).get('responseStatus')
                if response in ('accepted', 'declined', 'tentative', 'needsAction'):
                    guest['responseStatus'] = response
                p['attendees'].append(guest)
        if self.attendees:
            p.update(guestsCanModify=False, guestsCanInviteOthers=False)
        return p

    def matches(self, event, namespace):
        if not (owned(event, namespace) and private(event).get(KEY) == self.key
                and event.get('status') != 'cancelled' and event.get('summary', '') == self.summary
                and event.get('transparency', '') in ('', 'opaque')
                and (event.get('visibility', '') == self.visibility or (not event.get('visibility') and self.visibility == 'default'))
                and sorted(a.get('email', '').lower() for a in event.get('attendees', [])) == self.attendees
                and event.get('eventType', 'default') == 'default' and not event.get('recurringEventId')
                and all(event.get(k) is None for k in ('description', 'location', 'conferenceData', 'attachments', 'recurrence'))
                and event.get('reminders', {}).get('useDefault') is False):
            return False
        if self.attendees and (event.get('guestsCanModify', False) or event.get('guestsCanInviteOthers') is not False):
            return False
        try:
            return all(instant(event[k]['dateTime']) == instant(getattr(self, k)['dateTime']) for k in ('start', 'end'))
        except (SyncError, KeyError):
            return False


def source_busy(event, account, zone, policy):
    if (managed(event) or event.get('status') == 'cancelled'
            or event.get('transparency') == 'transparent'
            or event.get('eventType') in ('birthday', 'workingLocation')
            or any(a.get('email', '').lower() == account['owner_email'].lower() and a.get('responseStatus') == 'declined' for a in event.get('attendees', []))):
        return None
    if event.get('start', {}).get('date') and policy == 'out_of_office_only' and event.get('eventType') != 'outOfOffice':
        return None
    require(event.get('id'), 'Source event has no ID; refusing incomplete snapshot')
    start, end = (normalize_time(event.get(k), zone) for k in ('start', 'end'))
    require(instant(end['dateTime']) > instant(start['dateTime']), 'Invalid source interval; refusing incomplete snapshot')
    identity = event['id']
    if event.get('recurringEventId') is not None and event.get('originalStartTime') is not None:
        original = event['originalStartTime']
        # Match Rust EventTime serialization order and omission of None exactly.
        original = {k: original[k] for k in ('date', 'dateTime', 'timeZone') if original.get(k) is not None}
        identity = digest(event['recurringEventId'], json.dumps(original, ensure_ascii=False, separators=(',', ':')))
    return Busy(digest(account['source'], identity), start, end)
