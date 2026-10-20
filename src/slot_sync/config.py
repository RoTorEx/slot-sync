"""Strict, backward-compatible Gallendar TOML configuration."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import tomllib


class SyncError(Exception):
    """A safe diagnostic that contains no remote response or credential values."""


def require(condition, message):
    if not condition:
        raise SyncError(message)


def known_keys(value, allowed):
    require(isinstance(value, dict) and not (set(value) - set(allowed.split())),
            'Unknown or malformed configuration fields')


class Config:
    def __init__(self, data, path):
        self.data = deepcopy(data)
        self.path = Path(path).resolve()
        known_keys(data, 'service_account_key auth oauth namespace mirror_calendar_name horizon_days poll_seconds all_day_policy accounts routes auto_update')
        self.namespace = data.get('namespace', '')
        self.horizon_days = data.get('horizon_days', 0)
        self.poll_seconds = data.get('poll_seconds', 0)
        self.policy = data.get('all_day_policy')
        self.auth = data.get('auth', 'service_account')
        self.mirror_name = data.get('mirror_calendar_name')
        self.accounts = self.data.get('accounts', [])
        for a in self.accounts:
            known_keys(a, 'auth name owner_email source target retired_targets')
            a.setdefault('source', '')
            a.setdefault('target', '')
            a.setdefault('retired_targets', [])
        if 'routes' in data:
            self.routes = self.data['routes']
        else:
            self.routes = [{'from': a['name'], 'to': b['name'], 'mode': 'hidden'}
                           for a in self.accounts for b in self.accounts if a['name'] != b['name']]
        for r in self.routes:
            known_keys(r, 'from to mode hidden_title title prefix attendees')
            require(not ('title' in r and 'hidden_title' in r), 'Duplicate hidden title fields')
            r.setdefault('mode', 'visible')
            if r['mode'] == 'masked':
                r['mode'] = 'hidden'
            r.setdefault('hidden_title', r.get('title', 'Busy'))
            r.setdefault('prefix', '')
            r.setdefault('attendees', [])
        self.oauth = self.data.get('oauth')
        if self.oauth is not None:
            known_keys(self.oauth, 'client tokens_dir')
            require(set(self.oauth) == {'client', 'tokens_dir'}, 'OAuth needs client and tokens_dir')
            self.oauth = {k: self.resolve(v) for k, v in self.oauth.items()}
        self.service_key = self.resolve(data.get('service_account_key', ''))

    def resolve(self, value):
        p = Path(value)
        return p if p.is_absolute() else self.path.parent / p

    @classmethod
    def load(cls, path, validate=True):
        try:
            with open(path, 'rb') as f:
                data = tomllib.load(f)
            cfg = cls(data, path)
            if validate:
                cfg.validate()
            return cfg
        except SyncError:
            raise
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise SyncError('Invalid or unreadable config; compare with the example (values omitted)') from None

    def account(self, name):
        for a in self.accounts:
            if a['name'] == name:
                return a
        raise SyncError('Unknown account name')

    def sources(self):
        return [a for a in self.accounts if any(r['from'] == a['name'] for r in self.routes)]

    def targets(self):
        return [a for a in self.accounts if any(r['to'] == a['name'] for r in self.routes)]

    def auth_mode(self, account):
        return account.get('auth', self.auth)

    def window(self, now=None):
        start = now or datetime.now(timezone.utc)
        return start, start + timedelta(days=self.horizon_days)

    def validate(self):
        require(2 <= len(self.accounts) <= 4, 'Configure between 2 and 4 accounts')
        require(isinstance(self.namespace, str) and self.namespace.strip(), 'namespace must not be empty')
        require(type(self.horizon_days) is int and 1 <= self.horizon_days <= 30, 'horizon_days must be between 1 and 30')
        require(type(self.poll_seconds) is int and self.poll_seconds > 0, 'poll_seconds must be positive')
        require(self.policy in ('busy', 'out_of_office_only'), 'Select an explicit all_day_policy')
        require(self.auth in ('oauth', 'service_account'), 'Invalid authentication mode')
        names, owners, sources, targets = set(), set(), set(), set()
        for a in self.accounts:
            name, owner = a.get('name', ''), a.get('owner_email', '')
            require(isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_-]+', name), 'Invalid account alias')
            require(name not in names, 'Account names must be unique')
            require('@' in owner and owner.lower() not in owners, 'Each account needs a unique owner_email')
            require(self.auth_mode(a) in ('oauth', 'service_account'), 'Invalid account authentication mode')
            names.add(name)
            owners.add(owner.lower())
            for field, seen in [('source', sources), ('target', targets)]:
                value = a[field]
                require(isinstance(value, str), 'Calendar IDs must be strings')
                if value:
                    require(value.strip() and value != 'primary' and 'REPLACE' not in value, 'Use explicit calendar IDs without placeholders')
                    require(value not in seen, 'Calendar IDs must be unique within each role')
                    seen.add(value)
        require(not (sources & targets), 'Clone calendars must be separate from every source')
        require(self.routes, 'Configure at least one route')
        pairs, retired = set(), set()
        if self.mirror_name is not None:
            require(isinstance(self.mirror_name, str) and self.mirror_name.strip(), 'Named mirror must not be empty')
        configured = owners | {x.lower() for x in sources | targets}
        for r in self.routes:
            a, b = self.account(r['from']), self.account(r['to'])
            pair = (r['from'], r['to'])
            require(pair not in pairs and a != b, 'Duplicate route or self route')
            pairs.add(pair)
            require(a['source'] and (b['target'] or self.mirror_name), 'Route needs source and destination IDs')
            require(r['mode'] in ('visible', 'hidden', 'original'), 'Invalid route mode')
            require(isinstance(r['prefix'], str) and isinstance(r['hidden_title'], str), 'Titles and prefixes must be strings')
            require(r['mode'] != 'hidden' or r['hidden_title'].strip(), 'Hidden title must not be empty')
            if self.mirror_name or r['attendees']:
                require(self.auth_mode(b) == 'oauth', 'Named calendars and guests require destination OAuth')
            guests = set()
            for email in r['attendees']:
                require(isinstance(email, str) and re.fullmatch(r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~.-]+@[A-Za-z0-9.-]+", email), 'Invalid route guest email')
                local, domain = email.split('@')
                require(not local.startswith('.') and not local.endswith('.') and '..' not in local and all(label and not label.startswith('-') and not label.endswith('-') for label in domain.split('.')), 'Invalid route guest email')
                require(email.lower() not in guests | configured, 'Duplicate guest or invitation feedback loop')
                guests.add(email.lower())
        readers = {a['name'] for a in self.sources()}
        writers = {a['name'] for a in self.targets()}
        if self.mirror_name:
            require(not (readers & writers), 'Named mirrors require one-way account routes')
        for a in self.accounts:
            if a['retired_targets']:
                require(a['name'] in writers - readers and not self.mirror_name, 'Retired targets require explicit destination-only accounts')
            for calendar in a['retired_targets']:
                require(calendar.strip() and calendar != 'primary' and 'REPLACE' not in calendar and calendar not in sources | targets | retired and calendar.lower() not in owners, 'Retired targets must be unique separate secondary calendars')
                retired.add(calendar)
