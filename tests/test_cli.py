from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen
from slot_sync.cli import parser
from slot_sync.config import SyncError
from slot_sync import oauth
import test_sync


class CliTests(unittest.TestCase):
    def test_global_options_before_and_after_subcommand(self):
        p = parser()
        for argv in [['--config', '/tmp/a', '--json', 'sync'], ['sync', '--config', '/tmp/a', '--json']]:
            a = p.parse_args(argv)
            self.assertEqual(a.config, '/tmp/a')
            self.assertTrue(a.json)
            self.assertFalse(a.apply)

    def test_installed_style_setup_preserves_configuration(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, SLOT_SYNC_HOME=d)
            command = [sys.executable, '-m', 'slot_sync', 'setup', '--no-edit', '--json']
            first = json.loads(subprocess.check_output(command, env=env, text=True))
            path = Path(first['config'])
            original = path.read_bytes()
            second = json.loads(subprocess.check_output(command, env=env, text=True))
            self.assertFalse(second['created'])
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


class LoginTests(unittest.TestCase):
    def setUp(self):
        test_sync.OAuthTests.setUp(self)

    # Execute the real local HTTP callback below.
    def test_pkce_login_ignores_forged_callback_and_verifies_owner(self):
        result, errors, threads = {}, [], []
        def visit(url):
            query = parse_qs(urlsplit(url).query)
            result['challenge'] = query['code_challenge'][0]
            redirect = query['redirect_uri'][0]
            def browser():
                try:
                    try:
                        urlopen(redirect + '?' + urlencode({'state': 'forged', 'code': 'bad'}), timeout=5)
                    except HTTPError as e:
                        self.assertEqual(e.code, 400)
                    with urlopen(redirect + '?' + urlencode({'state': query['state'][0], 'code': 'accepted-code'}), timeout=5) as response:
                        self.assertEqual(response.status, 200)
                except Exception as e:
                    errors.append(e)
            t = threading.Thread(target=browser)
            threads.append(t); t.start()
        def transport(method, url, **kwargs):
            if url == oauth.TOKEN_URL:
                import base64, hashlib
                form = kwargs['form']
                self.assertEqual(form['code'], 'accepted-code')
                self.assertEqual(base64.urlsafe_b64encode(hashlib.sha256(form['code_verifier'].encode()).digest()).decode().rstrip('='), result['challenge'])
                return 200, {'access_token': 'access', 'refresh_token': 'new-offline', 'scope': ' '.join(oauth.scopes(self.cfg, self.a))}
            return 200, {'email': self.a['owner_email'], 'email_verified': True}
        with patch('slot_sync.oauth.open_browser', side_effect=visit), redirect_stdout(StringIO()):
            oauth.login(self.cfg, self.a, transport)
        for t in threads:
            t.join(5)
            self.assertFalse(t.is_alive())
        self.assertFalse(errors)
        self.assertEqual(json.loads(self.path.read_text())['refresh_token'], 'new-offline')

    def test_auth_alias_path_traversal_rejected_before_lock_creation(self):
        with self.assertRaises(SyncError):
            oauth.token_path(self.cfg, dict(self.a, name='../outside'))


if __name__ == '__main__':
    unittest.main()
