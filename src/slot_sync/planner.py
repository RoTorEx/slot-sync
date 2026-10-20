"""Read every calendar before producing any mutation; never write here."""
from copy import deepcopy
from dataclasses import dataclass, field
from .config import require
from .model import KEY, digest, instant, owned, private, source_busy


@dataclass
class Action:
    kind: str
    target: str
    event_id: str = ''
    busy: object = None


@dataclass
class Plan:
    namespace: str
    actions: list = field(default_factory=list)
    bindings: list = field(default_factory=list)
    counts: dict = field(default_factory=lambda: dict(create=0, update=0, delete=0, unchanged=0))

    def add(self, action):
        self.actions.append(action)
        self.counts[action.kind] += 1


def past(event, start):
    require(event.get('end', {}).get('dateTime'), 'Managed event has no end time; no changes applied')
    return instant(event['end']['dateTime']) <= start


def plan(api, cfg, window):
    result = Plan(digest(cfg.namespace))
    sources, targets, retired = {}, {}, {}
    for a in cfg.sources():
        snapshot = api.source(a['source'], window)
        require(snapshot['accessRole'] in ('reader', 'writer', 'writerWithoutPrivateAccess', 'owner'), 'Source needs full event read access; no changes applied')
        events = {}
        for e in snapshot['items']:
            busy = source_busy(e, a, snapshot['timeZone'], cfg.policy)
            if busy:
                events[busy.key] = (busy, e.get('summary', ''))
        sources[a['name']] = events
    for a in cfg.targets():
        snapshot = api.clones(a['target'], result.namespace)
        require(snapshot['accessRole'] in ('writer', 'writerWithoutPrivateAccess', 'owner'), 'Target needs write access; no changes applied')
        targets[a['name']] = snapshot['items']
        for calendar in a['retired_targets']:
            snapshot = api.clones(calendar, result.namespace)
            require(snapshot['accessRole'] == 'owner', 'Retired target must be owned; no changes applied')
            retired[calendar] = snapshot['items']
    for calendar, events in retired.items():
        for e in events:
            if owned(e, result.namespace) and e.get('status') != 'cancelled' and not past(e, window[0]):
                require(e.get('id'), 'Retired managed event has no ID')
                result.add(Action('delete', calendar, e['id']))
    for a in cfg.targets():
        desired = {}
        for r in cfg.routes:
            if r['to'] != a['name']:
                continue
            for key, (source, title) in sources[r['from']].items():
                busy = deepcopy(source)
                busy.summary = r['prefix'] + (r['hidden_title'] if r['mode'] == 'hidden' else title)
                busy.visibility = {'visible': 'public', 'hidden': 'private', 'original': 'default'}[r['mode']]
                busy.attendees = sorted(email.lower() for email in r['attendees'])
                desired[key] = busy
        seen = set()
        for e in sorted(targets[a['name']], key=lambda e: e.get('id', '')):
            if not owned(e, result.namespace) or e.get('status') == 'cancelled':
                continue
            require(e.get('id'), 'Managed event has no ID; no changes applied')
            if past(e, window[0]):
                continue
            key = private(e).get(KEY)
            if key in desired and key not in seen:
                seen.add(key)
                result.bindings.append((a['target'], key, e['id']))
                if desired[key].matches(e, result.namespace):
                    result.counts['unchanged'] += 1
                else:
                    result.add(Action('update', a['target'], e['id'], desired[key]))
            else:
                result.add(Action('delete', a['target'], e['id']))
        for key in sorted(desired.keys() - seen):
            result.add(Action('create', a['target'], busy=desired[key]))
    result.actions.sort(key=lambda a: a.kind == 'delete')
    return result
