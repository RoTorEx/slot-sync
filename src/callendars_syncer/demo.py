"""Offline four-account reconciliation demonstration."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from .config import Config, require
from .planner import plan


class Memory:
    def __init__(self):
        self.calendars = {}
        self.failure = None

    def source(self, calendar, window):
        return self.clones(calendar, '')

    def clones(self, calendar, namespace):
        require(calendar != self.failure, 'Simulated incomplete snapshot')
        return {'items': deepcopy(self.calendars.get(calendar, [])), 'timeZone': 'Europe/Warsaw', 'accessRole': 'owner'}

    def apply(self, planned):
        for a in planned.actions:
            events = self.calendars.setdefault(a.target, [])
            if a.kind == 'create':
                events.append(a.busy.payload('demo' + str(len(events)), planned.namespace))
            else:
                index = next(i for i, e in enumerate(events) if e['id'] == a.event_id)
                if a.kind == 'update':
                    events[index] = a.busy.payload(a.event_id, planned.namespace, events[index])
                else:
                    events.pop(index)


def fixture():
    accounts = [{'name': f'account-{i}', 'owner_email': f'owner-{i}@example.invalid', 'source': f'source-{i}', 'target': f'clone-{i}'} for i in range(4)]
    cfg = Config({'namespace': 'demo', 'horizon_days': 30, 'poll_seconds': 1800, 'all_day_policy': 'busy', 'accounts': accounts}, '/tmp/demo.toml')
    cfg.validate()
    api = Memory()
    start = datetime.now(timezone.utc) + timedelta(days=1)
    for a in cfg.accounts:
        api.calendars[a['source']] = [{'id': 'original', 'summary': 'Confidential title', 'description': 'Private context',
                                      'start': {'dateTime': start.isoformat()}, 'end': {'dateTime': (start + timedelta(minutes=30)).isoformat()}}]
    return cfg, api


def run():
    cfg, api = fixture()
    window = cfg.window()
    initial = plan(api, cfg, window)
    require(initial.counts['create'] == 12, 'Four-account demo failed')
    api.apply(initial)
    repeated = plan(api, cfg, window)
    require(not repeated.actions, 'Demo idempotency failed')
    e = api.calendars['source-0'][0]
    start = window[0] + timedelta(days=2)
    e.update(start={'dateTime': start.isoformat()}, end={'dateTime': (start + timedelta(minutes=30)).isoformat()})
    moved = plan(api, cfg, window)
    require(moved.counts['update'] == 3, 'Demo reschedule failed')
    api.apply(moved)
    api.calendars['source-0'] = []
    deleted = plan(api, cfg, window)
    require(deleted.counts['delete'] == 3, 'Demo cancellation failed')
    api.apply(deleted)
    return {'mode': 'offline-demo', 'google_validated': False, 'initial': initial.counts,
            'repeat': repeated.counts, 'reschedule': moved.counts, 'deletion': deleted.counts}
