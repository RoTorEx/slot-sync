"""Google API boundary: destination allowlists, complete reads and verified writes."""
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from .config import SyncError, require
from .model import KEY, owned, private
from . import oauth

BASE = 'https://www.googleapis.com/calendar/v3/'
SOURCE_FIELDS = 'nextPageToken,timeZone,accessRole,items(id,summary,status,eventType,transparency,start,end,recurringEventId,originalStartTime,attendees(email,responseStatus),extendedProperties)'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def http(method, url, token=None, payload=None, form=None, etag=None):
    headers = {}
    data = None
    if token:
        headers['Authorization'] = 'Bearer ' + token
    if payload is not None:
        data = json.dumps(payload).encode()
        headers['Content-Type'] = 'application/json'
    if form is not None:
        data = urlencode(form).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    if etag:
        headers['If-Match'] = etag
    try:
        try:
            response = build_opener(NoRedirect()).open(Request(url, data=data, headers=headers, method=method), timeout=30)
        except HTTPError as e:
            response = e
        with response:
            body = response.read(16 * 1024 * 1024 + 1)
            require(len(body) <= 16 * 1024 * 1024, 'Google response exceeds bounded page size')
            if not body:
                return response.code, {}
            try:
                value = json.loads(body)
            except ValueError:
                raise SyncError(f'Invalid Google response (HTTP {response.code}; contents omitted)') from None
            require(isinstance(value, dict), 'Google returned a malformed response')
            return response.code, value
    except (URLError, TimeoutError, OSError):
        raise SyncError('Google request failed (network or timeout); rerun to reconcile') from None


class Google:
    def __init__(self, cfg, transport=http):
        self.cfg, self.http, self.tokens = cfg, transport, {}
        self.write_targets = {a['target'] for a in cfg.targets()} if not cfg.mirror_name else set()
        self.cleanup_targets = {c for a in cfg.targets() for c in a['retired_targets']}
        service_token = None
        for a in cfg.accounts:
            if not any(a['name'] in (r['from'], r['to']) for r in cfg.routes):
                continue
            if cfg.auth_mode(a) == 'oauth':
                token = oauth.access_token(cfg, a, transport)
            else:
                if service_token is None:
                    try:
                        from google.oauth2 import service_account
                        from google.auth.transport.requests import Request as AuthRequest
                        credentials = service_account.Credentials.from_service_account_file(str(cfg.service_key), scopes=[oauth.EVENTS, oauth.FREEBUSY])
                        credentials.refresh(AuthRequest())
                        service_token = credentials.token
                    except Exception:
                        raise SyncError('Service-account authentication failed; check key, clock and Calendar API (details omitted)') from None
                token = service_token
            for key in [f"account:{a['name']}", a['owner_email'], a['source'], a['target'], *a['retired_targets']]:
                if key:
                    self.tokens[key] = token

    def resolve(self):
        if self.cfg.mirror_name:
            for a in self.cfg.targets():
                a['target'], _ = self.named_calendar(a['name'], self.cfg.mirror_name, False)
        self.cfg.validate()
        return self

    def request(self, calendar, method, path, payload=None, query=None, etag=None, mutation=False):
        if mutation:
            allowed = self.write_targets | (self.cleanup_targets if method == 'DELETE' else set())
            require(calendar in allowed, 'Refusing write outside resolved destination allowlist')
        require(calendar in self.tokens, 'No credentials configured for this calendar')
        return self.http(method, BASE + path + ('?' + urlencode(query) if query else ''), token=self.tokens[calendar], payload=payload, etag=etag)

    @staticmethod
    def events_path(calendar, event_id=None):
        path = 'calendars/' + quote(calendar, safe='') + '/events'
        return path + '/' + quote(event_id, safe='') if event_id else path

    def list_events(self, calendar, window=None, namespace=None):
        query = {'maxResults': 2500, 'showDeleted': 'false', 'singleEvents': 'true' if window else 'false'}
        if window:
            query.update(timeMin=window[0].isoformat(), timeMax=window[1].isoformat(), fields=SOURCE_FIELDS)
        if namespace:
            query['privateExtendedProperty'] = 'gallendarNamespace=' + namespace
        result, seen = {'items': []}, set()
        while True:
            status, page = self.request(calendar, 'GET', self.events_path(calendar), query=query)
            require(status == 200, f'Cannot list Google events (HTTP {status}); no changes applied')
            require(isinstance(page.get('items', []), list), 'Malformed Google page; no changes applied')
            result['items'].extend(page.get('items', []))
            for field in ('timeZone', 'accessRole'):
                if field in page:
                    result[field] = page[field]
            token = page.get('nextPageToken')
            if not token:
                break
            require(isinstance(token, str) and token not in seen, 'Repeated or invalid pagination token; no changes applied')
            seen.add(token)
            query['pageToken'] = token
        require(result.get('timeZone') and result.get('accessRole'), 'Incomplete calendar metadata; no changes applied')
        return result

    def source(self, calendar, window):
        return self.list_events(calendar, window=window)

    def clones(self, calendar, namespace):
        return self.list_events(calendar, namespace=namespace)

    def get(self, calendar, event_id, tombstones=False):
        status, event = self.request(calendar, 'GET', self.events_path(calendar, event_id))
        if status in (404, 410):
            return {'id': event_id, 'status': 'cancelled'} if tombstones and status == 410 else None
        require(status == 200, f'Cannot read Google event (HTTP {status})')
        return event

    def verify(self, calendar, event_id, busy, namespace):
        event = self.get(calendar, event_id)
        require(event is not None and busy.matches(event, namespace), 'Saved event differs on read-back; stopping')

    def create(self, calendar, busy, namespace, state):
        require(calendar in self.write_targets, 'Refusing create outside destinations')
        event_id = state.creation_id(namespace, calendar, busy.key)
        existing = self.get(calendar, event_id, tombstones=True)
        if existing and existing.get('status') == 'cancelled':
            state.abandon_cancelled(namespace, calendar, busy.key)
            event_id = state.creation_id(namespace, calendar, busy.key)
            existing = self.get(calendar, event_id, tombstones=True)
        if existing:
            require(owned(existing, namespace) and private(existing).get(KEY) == busy.key, 'Creation identity belongs to another event; stopping')
            if not busy.matches(existing, namespace):
                self.update(calendar, event_id, busy, namespace)
        else:
            status, _ = self.request(calendar, 'POST', self.events_path(calendar), payload=busy.payload(event_id, namespace),
                                     query={'sendUpdates': 'all' if busy.attendees else 'none'}, mutation=True)
            require(200 <= status < 300 or status == 409, f'Create failed (HTTP {status}); rerun to reconcile the same ID')
        self.verify(calendar, event_id, busy, namespace)
        state.remember(namespace, calendar, busy.key, event_id)

    def update(self, calendar, event_id, busy, namespace):
        current = self.get(calendar, event_id)
        require(current and owned(current, namespace) and private(current).get(KEY) == busy.key, 'Event disappeared or changed ownership; refusing overwrite')
        require(current.get('etag'), 'Missing event version; refusing unprotected update')
        status, _ = self.request(calendar, 'PUT', self.events_path(calendar, event_id), payload=busy.payload(event_id, namespace, current),
                                 query={'sendUpdates': 'all' if busy.attendees or current.get('attendees') else 'none'}, etag=current['etag'], mutation=True)
        require(200 <= status < 300, f'Update failed (HTTP {status}); rebuild plan before retrying')
        self.verify(calendar, event_id, busy, namespace)

    def delete(self, calendar, event_id, namespace):
        current = self.get(calendar, event_id)
        if not current or current.get('status') == 'cancelled':
            return
        require(owned(current, namespace), 'Ownership changed; refusing deletion')
        require(current.get('etag'), 'Missing event version; refusing unprotected deletion')
        status, _ = self.request(calendar, 'DELETE', self.events_path(calendar, event_id),
                                 query={'sendUpdates': 'all' if current.get('attendees') else 'none'}, etag=current['etag'], mutation=True)
        require(200 <= status < 300 or status in (404, 410), f'Deletion failed (HTTP {status})')
        saved = self.get(calendar, event_id)
        require(saved is None or saved.get('status') == 'cancelled', 'Deleted event remains on read-back; stopping')

    def named_calendar(self, account, name, create):
        key, matches, seen = 'account:' + account, [], set()
        query = {'showHidden': 'true', 'fields': 'nextPageToken,items(id,summary,accessRole,primary)'}
        while True:
            status, page = self.request(key, 'GET', 'users/me/calendarList', query=query)
            require(status == 200 and isinstance(page.get('items'), list), 'Cannot list destination calendars')
            matches.extend(c for c in page['items'] if c.get('summary') == name)
            token = page.get('nextPageToken')
            if not token:
                break
            require(token not in seen, 'Repeated calendar-list pagination token')
            seen.add(token)
            query['pageToken'] = token
        require(len(matches) <= 1, 'Multiple matching named calendars; resolve ambiguity first')
        created = not matches
        if matches:
            calendar = matches[0]
            require(not calendar.get('primary') and calendar.get('accessRole') == 'owner', 'Named mirror must be an owned secondary calendar')
        else:
            require(create, 'Named mirror is missing; run calendar ensure explicitly')
            status, calendar = self.request(key, 'POST', 'calendars', payload={'summary': name, 'timeZone': 'Europe/Warsaw'})
            require(200 <= status < 300 and calendar.get('id'), 'Calendar creation failed; inspect before retrying')
            status, check = self.request(key, 'GET', 'calendars/' + quote(calendar['id'], safe=''))
            require(status == 200 and check.get('id') == calendar['id'] and check.get('summary') == name and check.get('timeZone') == 'Europe/Warsaw', 'Created calendar differs on read-back')
        calendar_id = calendar.get('id')
        require(calendar_id and calendar_id != 'primary', 'Named mirror needs an explicit calendar ID')
        self.tokens[calendar_id] = self.tokens[key]
        self.write_targets.add(calendar_id)
        return calendar_id, created

    def availability(self, calendar, start, end):
        status, result = self.request(calendar, 'POST', 'freeBusy', payload={'timeMin': start.isoformat(), 'timeMax': end.isoformat(), 'items': [{'id': calendar}]})
        require(status == 200, 'Free/busy request failed')
        item = result.get('calendars', {}).get(calendar, {})
        require(not item.get('errors') and isinstance(item.get('busy'), list), 'Availability is unknown; incomplete response')
        return item['busy']
