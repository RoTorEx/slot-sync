from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from slot_sync.config import Config, SyncError
from slot_sync.demo import Memory, fixture, run
from slot_sync.model import Busy, KEY, digest, instant, normalize_time, owned, source_busy
from slot_sync.planner import plan
from slot_sync.storage import State, atomic_json, lock
from slot_sync import health, oauth
from slot_sync.google import Google
from slot_sync.runner import sync


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.cfg, self.api = fixture()
        self.window = self.cfg.window()

    def test_four_account_demo(self):
        self.assertEqual(run()['repeat']['create'], 0)

    def test_current_directed_routes_and_prefix_change_keep_ids(self):
        self.cfg.routes = [dict(self.cfg.routes[0], mode='visible', prefix='[Source] ')]
        self.api.apply(plan(self.api, self.cfg, self.window))
        target = self.cfg.targets()[0]['target']
        old = deepcopy(self.api.calendars[target])
        self.cfg.routes[0]['prefix'] = '[Changed] '
        p = plan(self.api, self.cfg, self.window)
        self.assertEqual(p.counts['update'], 1)
        self.api.apply(p)
        self.assertEqual(self.api.calendars[target][0]['id'], old[0]['id'])
        self.assertEqual(self.api.calendars[target][0]['visibility'], 'public')
        self.assertFalse(plan(self.api, self.cfg, self.window).actions)

    def test_hidden_mode_and_empty_visible_title(self):
        r = self.cfg.routes[0]
        self.cfg.routes = [r]
        r.update(mode='hidden', hidden_title='Unavailable', prefix='Work: ')
        p = plan(self.api, self.cfg, self.window)
        self.assertEqual(p.actions[0].busy.summary, 'Work: Unavailable')
        self.assertEqual(p.actions[0].busy.visibility, 'private')
        r['mode'] = 'visible'
        self.api.calendars['source-0'][0]['summary'] = ''
        self.assertEqual(plan(self.api, self.cfg, self.window).actions[0].busy.summary, 'Work: ')

    def test_excludes_free_cancelled_declined_and_managed(self):
        source = self.api.calendars['source-0'][0]
        account = self.cfg.accounts[0]
        variants = [{'transparency': 'transparent'}, {'status': 'cancelled'}, {'eventType': 'birthday'}, {'eventType': 'workingLocation'}, {'attendees': [{'email': account['owner_email'].upper(), 'responseStatus': 'declined'}]}, {'extendedProperties': {'private': {'gallendar': 'v1'}}}]
        for value in variants:
            with self.subTest(value=value):
                e = dict(source, **value)
                self.assertIsNone(source_busy(e, account, 'Europe/Warsaw', 'busy'))
        e = dict(source, attendees=[{'email': 'someone@example.invalid', 'responseStatus': 'declined'}])
        self.assertIsNotNone(source_busy(e, account, 'Europe/Warsaw', 'busy'))

    def test_all_day_dst_and_policy(self):
        e = {'id': 'day', 'start': {'date': '2026-03-29'}, 'end': {'date': '2026-03-30'}}
        b = source_busy(e, self.cfg.accounts[0], 'Europe/Warsaw', 'busy')
        self.assertEqual(instant(b.end['dateTime']) - instant(b.start['dateTime']), timedelta(hours=23))
        self.assertIsNone(source_busy(e, self.cfg.accounts[0], 'Europe/Warsaw', 'out_of_office_only'))
        e['eventType'] = 'outOfOffice'
        self.assertIsNotNone(source_busy(e, self.cfg.accounts[0], 'Europe/Warsaw', 'out_of_office_only'))

    def test_nonexistent_all_day_boundary_rejected(self):
        with self.assertRaises(SyncError):
            normalize_time({'date': '2011-12-30'}, 'Pacific/Apia')

    def test_invalid_or_missing_offsets_and_intervals_rejected(self):
        for time in ['2026-01-01T10:00:00', 'invalid']:
            with self.assertRaises(SyncError):
                instant(time)
        e = self.api.calendars['source-0'][0]
        e['end'] = e['start']
        with self.assertRaises(SyncError):
            plan(self.api, self.cfg, self.window)

    def test_digest_matches_legacy_length_prefixed_utf8(self):
        parts = ['a', 'é', 'test']
        blob = b''.join(len(p.encode()).to_bytes(8, 'big') + p.encode() for p in parts)
        self.assertEqual(digest(*parts), hashlib.sha256(blob).hexdigest())
        self.assertNotEqual(digest('ab', 'c'), digest('a', 'bc'))

    def test_moved_occurrence_retains_legacy_key(self):
        e = self.api.calendars['source-0'][0]
        e.update(recurringEventId='series', originalStartTime={'dateTime': e['start']['dateTime'], 'timeZone': 'Europe/Warsaw'})
        before = source_busy(e, self.cfg.accounts[0], 'UTC', 'busy')
        expected = digest('source-0', digest('series', json.dumps(e['originalStartTime'], separators=(',', ':'))))
        self.assertEqual(before.key, expected)
        e['start'] = {'dateTime': (self.window[0] + timedelta(days=2)).isoformat()}
        e['end'] = {'dateTime': (self.window[0] + timedelta(days=2, hours=1)).isoformat()}
        self.assertEqual(source_busy(e, self.cfg.accounts[0], 'UTC', 'busy').key, before.key)

    def test_no_source_context_in_payload_and_rsvp_survives(self):
        p = plan(self.api, self.cfg, self.window)
        b = p.actions[0].busy
        b.attendees = ['guest@example.invalid']
        current = {'attendees': [{'email': 'GUEST@example.invalid', 'responseStatus': 'accepted'}]}
        payload = b.payload('copy', p.namespace, current)
        self.assertEqual(payload['attendees'][0]['responseStatus'], 'accepted')
        self.assertNotIn('description', payload)
        self.assertNotIn('location', payload)
        self.assertNotIn('conferenceData', payload)
        self.assertFalse(payload['guestsCanInviteOthers'])
        self.assertTrue(b.matches(payload, p.namespace))
        payload['description'] = 'pollution'
        self.assertFalse(b.matches(payload, p.namespace))

    def test_managed_duplicates_cleaned_but_foreign_and_past_preserved(self):
        self.api.apply(plan(self.api, self.cfg, self.window))
        events = self.api.calendars['clone-0']
        duplicate = deepcopy(events[0]); duplicate['id'] = 'zz-duplicate'
        past = deepcopy(events[0]); past['id'] = 'past'; past['end'] = {'dateTime': (self.window[0] - timedelta(hours=1)).isoformat()}
        foreign = dict(deepcopy(events[0]), id='foreign', extendedProperties={})
        events.extend([duplicate, past, foreign])
        p = plan(self.api, self.cfg, self.window)
        deletes = [a.event_id for a in p.actions if a.kind == 'delete']
        self.assertEqual(deletes, ['zz-duplicate'])

    def test_future_orphan_removed_and_read_failure_prevents_plan(self):
        self.api.apply(plan(self.api, self.cfg, self.window))
        self.api.calendars['source-0'] = []
        self.assertEqual(plan(self.api, self.cfg, self.window).counts['delete'], 3)
        for calendar in ['source-1', 'clone-0']:
            self.api.failure = calendar
            with self.assertRaises(SyncError):
                plan(self.api, self.cfg, self.window)

    def test_retired_cleanup_follows_new_creates_and_preserves_past(self):
        self.cfg.routes = [self.cfg.routes[0]]
        a = self.cfg.targets()[0]
        a['retired_targets'] = ['old-secondary']
        p = plan(self.api, self.cfg, self.window)
        e = p.actions[0].busy.payload('old', p.namespace)
        self.api.calendars['old-secondary'] = [e]
        p = plan(self.api, self.cfg, self.window)
        self.assertEqual([a.kind for a in p.actions], ['create', 'delete'])
        self.api.failure = 'old-secondary'
        with self.assertRaises(SyncError):
            plan(self.api, self.cfg, self.window)


class ConfigurationTests(unittest.TestCase):
    def test_invalid_feedback_routes_and_bounds(self):
        for mutation in [lambda d: d.update(horizon_days=0), lambda d: d.update(horizon_days=31), lambda d: d.update(poll_seconds=0), lambda d: d['accounts'][0].update(target='source-1'), lambda d: d['accounts'][0].update(name='../escape')]:
            cfg, _ = fixture(); d = deepcopy(cfg.data); mutation(d)
            with self.assertRaises(SyncError):
                Config(d, '/tmp/test.toml').validate()

    def test_guest_feedback_and_duplicate_guests_rejected(self):
        cfg, _ = fixture()
        cfg.auth = 'oauth'
        cfg.routes = [cfg.routes[0]]
        for guests in [[cfg.accounts[0]['owner_email']], ['a@b.com', 'A@b.com'], ['bad email@b.com']]:
            cfg.routes[0]['attendees'] = guests
            with self.assertRaises(SyncError):
                cfg.validate()

    def test_relative_oauth_paths_and_unknown_fields(self):
        cfg, _ = fixture()
        data = dict(cfg.data, auth='oauth', oauth={'client': 'secrets/client.json', 'tokens_dir': 'secrets/oauth'})
        c = Config(data, '/tmp/home/config.toml')
        self.assertEqual(c.oauth['client'], Path('/tmp/home/secrets/client.json').resolve())
        with self.assertRaises(SyncError):
            Config(dict(data, typo=True), '/tmp/test.toml')


class PersistenceTests(unittest.TestCase):
    def test_creation_id_survives_restart_and_rotates_after_confirmed_deletion(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.sqlite3'
            s = State(path)
            old = s.creation_id('ns', 'cal', 'key'); s.close()
            s = State(path)
            self.assertEqual(s.creation_id('ns', 'cal', 'key'), old)
            s.remember('ns', 'cal', 'key', old)
            self.assertNotEqual(s.creation_id('ns', 'cal', 'key'), old)
            s.close()
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_lock_blocks_another_handle(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'config.lock'
            with lock(p):
                with self.assertRaises(SyncError):
                    with lock(p):
                        self.fail('lock was not exclusive')

    def test_atomic_health_preserves_success_and_hides_error(self):
        with tempfile.TemporaryDirectory() as d:
            a = health.complete(d, 1800)
            b = health.complete(d, 1800, oauth.ReauthorizationRequired('work'))
            self.assertEqual(b['last_success_at'], a['last_success_at'])
            self.assertEqual(b['started_at'], a['started_at'])
            self.assertEqual(b['error_kind'], 'reauth_required')
            self.assertEqual(b['account'], 'work')
            c = health.complete(d, 1800, SyncError('private secret'))
            self.assertNotIn('secret', json.dumps(c))
            self.assertIsNone(health.complete(d, 1800)['error_kind'])
            self.assertEqual((Path(d) / 'health.json').stat().st_mode & 0o777, 0o644)

    def test_audit_failure_stops_before_any_mutation(self):
        cfg, api = fixture()
        with tempfile.TemporaryDirectory() as d:
            with patch('slot_sync.runner.Config.load', return_value=cfg), patch('slot_sync.runner.Google', return_value=api), patch('slot_sync.runner.audit', side_effect=OSError('disk full')):
                api.resolve = lambda: api
                with self.assertRaises(OSError):
                    sync(Path(d) / 'config.toml', Path(d) / 'state.sqlite3', Path(d) / 'logs', apply=True)
            self.assertFalse(any(k.startswith('clone') for k in api.calendars))


class OAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.cfg, _ = fixture()
        self.cfg.auth = 'oauth'
        root = Path(self.temp.name)
        self.cfg.oauth = {'client': root / 'client.json', 'tokens_dir': root / 'tokens'}
        atomic_json(self.cfg.oauth['client'], {'installed': {'client_id': 'test.apps.googleusercontent.com', 'client_secret': 'secret'}})
        self.a = self.cfg.accounts[0]
        self.path = oauth.token_path(self.cfg, self.a)
        self.saved = {'client_id': 'test.apps.googleusercontent.com', 'email': self.a['owner_email'], 'refresh_token': 'old-token', 'scopes': oauth.scopes(self.cfg, self.a)}
        atomic_json(self.path, self.saved)

    def test_refresh_preserves_and_rotates_credentials(self):
        self.assertEqual(oauth.access_token(self.cfg, self.a, lambda *_a, **_k: (200, {'access_token': 'access'})), 'access')
        self.assertEqual(json.loads(self.path.read_text())['refresh_token'], 'old-token')
        oauth.access_token(self.cfg, self.a, lambda *_a, **_k: (200, {'access_token': 'access', 'refresh_token': 'new-token'}))
        self.assertEqual(json.loads(self.path.read_text())['refresh_token'], 'new-token')

    def test_invalid_grant_is_reauth_but_transient_error_is_not(self):
        original = self.path.read_bytes()
        with self.assertRaises(oauth.ReauthorizationRequired):
            oauth.access_token(self.cfg, self.a, lambda *_a, **_k: (400, {'error': 'invalid_grant', 'private': 'secret'}))
        with self.assertRaises(SyncError) as caught:
            oauth.access_token(self.cfg, self.a, lambda *_a, **_k: (503, {'private': 'secret'}))
        self.assertNotIsInstance(caught.exception, oauth.ReauthorizationRequired)
        self.assertNotIn('secret', str(caught.exception))
        self.assertEqual(self.path.read_bytes(), original)

    def test_wrong_owner_or_client_or_scopes_never_contacts_network(self):
        for update in [{'email': 'wrong@example.invalid'}, {'client_id': 'wrong'}, {'scopes': []}]:
            atomic_json(self.path, dict(self.saved, **update))
            with self.assertRaises(oauth.ReauthorizationRequired):
                oauth.access_token(self.cfg, self.a, lambda *_a, **_k: self.fail('network called'))


class ApiTests(unittest.TestCase):
    def api(self, transport):
        api = object.__new__(Google)
        api.http = transport
        api.tokens = {'target': 'target-token', 'source': 'source-token', 'retired': 'target-token'}
        api.write_targets = {'target'}
        api.cleanup_targets = {'retired'}
        return api

    def test_complete_pagination_and_repeated_token_rejection(self):
        calls = []
        def transport(method, url, **kwargs):
            calls.append((url, kwargs))
            result = {'items': [{'id': str(len(calls))}], 'timeZone': 'UTC', 'accessRole': 'reader'}
            if len(calls) == 1:
                result['nextPageToken'] = 'page2'
            return 200, result
        api = self.api(transport)
        self.assertEqual(len(api.source('source', (datetime.now(timezone.utc), datetime.now(timezone.utc)))['items']), 2)
        self.assertIn('singleEvents=true', calls[0][0])
        self.assertEqual(calls[0][1]['token'], 'source-token')
        api.http = lambda *_a, **_k: (200, {'items': [], 'nextPageToken': 'same', 'timeZone': 'UTC', 'accessRole': 'owner'})
        with self.assertRaises(SyncError):
            api.clones('target', 'ns')

    def test_failed_second_page_is_not_empty_success(self):
        replies = iter([(200, {'items': [], 'nextPageToken': 'p'}), (503, {})])
        with self.assertRaises(SyncError):
            self.api(lambda *_a, **_k: next(replies)).clones('target', 'ns')

    def test_source_and_retired_mutation_allowlists(self):
        api = self.api(lambda *_a, **_k: self.fail('network called'))
        for cal in ['source', 'retired']:
            with self.assertRaises(SyncError):
                api.request(cal, 'POST', api.events_path(cal), mutation=True)

    def test_uncertain_create_reuses_saved_event_without_second_post(self):
        saved, posts = {}, []
        b = Busy('key', {'dateTime': '2026-10-21T10:00:00+00:00'}, {'dateTime': '2026-10-21T11:00:00+00:00'})
        def transport(method, url, **kwargs):
            if method == 'POST':
                posts.append(kwargs['payload']['id'])
                saved.update(kwargs['payload'])
                raise SyncError('lost response')
            return (200, deepcopy(saved)) if saved else (404, {})
        api = self.api(transport)
        with tempfile.TemporaryDirectory() as d:
            state = State(Path(d) / 'state.sqlite3')
            with self.assertRaises(SyncError):
                api.create('target', b, 'ns', state)
            api.create('target', b, 'ns', state)
            self.assertEqual(len(posts), 1)
            state.close()

    def test_update_uses_etag_preserves_guest_response_and_verifies(self):
        b = Busy('key', {'dateTime': '2026-10-21T10:00:00+00:00'}, {'dateTime': '2026-10-21T11:00:00+00:00'}, attendees=['guest@example.invalid'])
        current = b.payload('copy', 'ns'); current['etag'] = 'old-version'
        current['attendees'][0]['responseStatus'] = 'accepted'; current['description'] = 'private'
        calls = []
        def transport(method, url, **kwargs):
            calls.append((method, kwargs))
            if method == 'PUT':
                self.assertEqual(kwargs['etag'], 'old-version')
                self.assertEqual(kwargs['payload']['attendees'][0]['responseStatus'], 'accepted')
                self.assertNotIn('description', kwargs['payload'])
                current.clear(); current.update(kwargs['payload'])
            return 200, deepcopy(current)
        self.api(transport).update('target', 'copy', b, 'ns')
        self.assertEqual([m for m, _ in calls], ['GET', 'PUT', 'GET'])

    def test_foreign_event_and_failed_precondition_stop_mutations(self):
        b = Busy('key', {'dateTime': '2026-10-21T10:00:00+00:00'}, {'dateTime': '2026-10-21T11:00:00+00:00'})
        api = self.api(lambda *_a, **_k: (200, {'id': 'foreign'}))
        with self.assertRaises(SyncError):
            api.update('target', 'foreign', b, 'ns')
        with self.assertRaises(SyncError):
            api.delete('target', 'foreign', 'ns')
        e = b.payload('copy', 'ns'); e['etag'] = 'old'
        api.http = lambda method, *_a, **_k: (200, e) if method == 'GET' else (412, {})
        with self.assertRaises(SyncError):
            api.update('target', 'copy', b, 'ns')

    def test_freebusy_errors_are_not_free_time(self):
        api = self.api(lambda *_a, **_k: (200, {'calendars': {'source': {'errors': [{'reason': 'forbidden'}]}}}))
        with self.assertRaises(SyncError):
            api.availability('source', datetime.now(timezone.utc), datetime.now(timezone.utc))


if __name__ == '__main__':
    unittest.main()


class MigrationTests(unittest.TestCase):
    def test_unchanged_legacy_events_are_adopted_into_sqlite(self):
        cfg, api = fixture()
        api.apply(plan(api, cfg, cfg.window()))
        api.resolve = lambda: api
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'state.sqlite3'
            with patch('slot_sync.runner.Config.load', return_value=cfg), patch('slot_sync.runner.Google', return_value=api):
                result = sync(Path(d) / 'config.toml', path, Path(d) / 'logs', apply=True)
            self.assertEqual(result['changes']['unchanged'], 12)
            s = State(path)
            self.assertEqual(s.db.execute('SELECT count(*) FROM identities WHERE confirmed=1').fetchone()[0], 12)
            self.assertEqual(s.db.execute('SELECT outcome FROM passes').fetchone()[0], 'success')
            s.close()

    def test_pending_creation_with_explicit_tombstone_gets_new_id(self):
        b = Busy('key', {'dateTime': '2026-10-21T10:00:00+00:00'}, {'dateTime': '2026-10-21T11:00:00+00:00'})
        with tempfile.TemporaryDirectory() as d:
            s = State(Path(d) / 'state.sqlite3')
            old = s.creation_id('ns', 'target', b.key)
            saved = {}
            def transport(method, url, **kwargs):
                if method == 'GET' and url.endswith('/' + old):
                    return 410, {}
                if method == 'POST':
                    saved.update(kwargs['payload'])
                    return 200, deepcopy(saved)
                return (200, deepcopy(saved)) if saved else (404, {})
            ApiTests().api(transport).create('target', b, 'ns', s)
            self.assertNotEqual(saved['id'], old)
            s.close()
