"""Desktop OAuth PKCE login and refresh, preserving Gallendar's token format."""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import re
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit
import webbrowser
from .config import SyncError, require
from .storage import atomic_json, lock

TOKEN_URL = 'https://oauth2.googleapis.com/token'
USERINFO_URL = 'https://openidconnect.googleapis.com/v1/userinfo'
EVENTS = 'https://www.googleapis.com/auth/calendar.events'
FREEBUSY = EVENTS + '.freebusy'


class ReauthorizationRequired(SyncError):
    def __init__(self, account):
        self.account = account
        super().__init__(f'OAuth account {account} requires sign-in; run callendars-syncer auth login --account {account}')


def scopes(cfg, a):
    reader = any(r['from'] == a['name'] for r in cfg.routes)
    writer = any(r['to'] == a['name'] for r in cfg.routes)
    require(reader or writer, 'Account is not used by a route')
    result = ['openid', 'email', EVENTS if writer else EVENTS + '.readonly', FREEBUSY]
    if writer and cfg.mirror_name:
        result += ['https://www.googleapis.com/auth/calendar.calendarlist.readonly', 'https://www.googleapis.com/auth/calendar.calendars']
    return result


def scopes_present(granted, required):
    available = set(granted)
    if 'https://www.googleapis.com/auth/userinfo.email' in available:
        available.add('email')
    if EVENTS in available:
        available.add(EVENTS + '.readonly')
    return set(required) <= available


def client(cfg):
    require(cfg.oauth is not None, 'Configure [oauth] client and tokens_dir')
    try:
        c = json.loads(cfg.oauth['client'].read_text())['installed']
        require(c['client_id'].endswith('.apps.googleusercontent.com') and c['client_secret'], 'Invalid Desktop OAuth client')
        return c
    except (OSError, ValueError, KeyError, TypeError):
        raise SyncError('Invalid or missing Desktop OAuth client JSON (contents omitted)') from None


def token_path(cfg, a):
    require(cfg.oauth is not None, 'Configure [oauth] first')
    require(isinstance(a.get('name'), str) and re.fullmatch(r'[A-Za-z0-9_-]+', a['name']), 'Invalid account alias')
    return cfg.oauth['tokens_dir'] / (a['name'] + '.json')


def check_saved(saved, c, a, required):
    require(saved.get('client_id') == c['client_id'] and saved.get('email', '').lower() == a['owner_email'].lower()
            and saved.get('refresh_token') and scopes_present(saved.get('scopes', []), required), 'Saved OAuth identity or permissions are invalid')


def exchange(http, form, account):
    status, result = http('POST', TOKEN_URL, form=form)
    if status == 400 and result.get('error') == 'invalid_grant':
        raise ReauthorizationRequired(account)
    require(200 <= status < 300 and result.get('access_token'), f'OAuth token exchange failed (HTTP {status}); response omitted')
    return result


def access_token(cfg, a, http):
    path = token_path(cfg, a)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    with lock(path.with_suffix('.lock')):
        c = client(cfg)
        try:
            saved = json.loads(path.read_text())
            required = scopes(cfg, a)
            check_saved(saved, c, a, required)
        except (OSError, ValueError, TypeError, AttributeError, SyncError):
            raise ReauthorizationRequired(a['name']) from None
        result = exchange(http, {'grant_type': 'refresh_token', 'client_id': c['client_id'],
                                 'client_secret': c['client_secret'], 'refresh_token': saved['refresh_token']}, a['name'])
        if 'scope' in result:
            granted = result['scope'].split()
            if not scopes_present(granted, required):
                raise ReauthorizationRequired(a['name'])
            saved['scopes'] = granted
        if 'refresh_token' in result:
            require(result['refresh_token'], 'Google returned empty offline credentials')
            saved['refresh_token'] = result['refresh_token']
            atomic_json(path, saved)
        return result['access_token']


def login(cfg, a, http, no_browser=False):
    require(cfg.auth_mode(a) == 'oauth', 'Select OAuth authentication first')
    require('@' in a['owner_email'] and 'REPLACE' not in a['owner_email'], 'Set the real account owner before login')
    path = token_path(cfg, a)
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    with lock(path.with_suffix('.lock')):
        c = client(cfg)
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        outcome = {}

        class Callback(BaseHTTPRequestHandler):
            def setup(self):
                self.request.settimeout(2)
                super().setup()

            def log_message(self, *_args):
                pass

            def do_GET(self):
                p = urlsplit(self.path)
                q = parse_qs(p.query, keep_blank_values=True)
                valid = p.path == '/callback' and q.get('state') == [state]
                if valid and q.get('error'):
                    outcome['denied'] = True
                accepted = valid and len(q.get('code', [])) == 1 and bool(q['code'][0]) and not q.get('error')
                if accepted:
                    outcome['code'] = q['code'][0]
                self.send_response(200 if accepted else 400)
                self.send_header('Content-Type', 'text/plain')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(b'Return to the terminal to check authorization.')

        with HTTPServer(('127.0.0.1', 0), Callback) as server:
            server.timeout = 1
            redirect = f'http://127.0.0.1:{server.server_port}/callback'
            required = scopes(cfg, a)
            url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
                'client_id': c['client_id'], 'redirect_uri': redirect, 'response_type': 'code',
                'scope': ' '.join(required), 'access_type': 'offline', 'prompt': 'consent select_account',
                'login_hint': a['owner_email'], 'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256'})
            print('Open this URL on this computer to authorize account ' + a['name'] + ':\n' + url, flush=True)
            if not no_browser:
                webbrowser.open(url)
            deadline = time.monotonic() + 180
            while not outcome and time.monotonic() < deadline:
                server.handle_request()
            require('code' in outcome, 'OAuth denied or timed out; previous credentials preserved')
        result = exchange(http, {'grant_type': 'authorization_code', 'client_id': c['client_id'],
                                'client_secret': c['client_secret'], 'code': outcome['code'],
                                'redirect_uri': redirect, 'code_verifier': verifier}, a['name'])
        status, identity = http('GET', USERINFO_URL, token=result['access_token'])
        require(status == 200 and identity.get('email_verified') is True and identity.get('email', '').lower() == a['owner_email'].lower(), 'Wrong Google identity; previous credentials preserved')
        saved = {'client_id': c['client_id'], 'email': identity['email'], 'refresh_token': result.get('refresh_token'), 'scopes': result.get('scope', '').split()}
        check_saved(saved, c, a, required)
        atomic_json(path, saved)
        return {'account': a['name'], 'authorized': True}


def status(cfg):
    result = []
    for a in cfg.accounts:
        if cfg.auth_mode(a) != 'oauth':
            result.append({'account': a['name'], 'auth': 'service_account'})
            continue
        try:
            check_saved(json.loads(token_path(cfg, a).read_text()), client(cfg), a, scopes(cfg, a))
            valid = True
        except (OSError, ValueError, KeyError, TypeError, SyncError):
            valid = False
        result.append({'account': a['name'], 'auth': 'oauth', 'credentials_present': valid, 'remote_validity_checked': False})
    return {'accounts': result}
