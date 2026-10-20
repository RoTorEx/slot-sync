"""One executable for operators and the system scheduler."""
import argparse
from datetime import datetime
from importlib.resources import files
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo
from . import __version__, oauth
from .config import Config, SyncError, require
from .google import Google, http
from .model import digest, instant
from .runner import sync


def paths(args):
    home = Path(os.environ.get('SLOT_SYNC_HOME', Path.home() / '.config/slot-sync'))
    config = Path(args.config or os.environ.get('SLOT_SYNC_CONFIG') or os.environ.get('GALLENDAR_CONFIG') or home / 'config.toml')
    state = Path(args.state or os.environ.get('SLOT_SYNC_STATE') or home / 'state.sqlite3')
    logs = Path(os.environ.get('SLOT_SYNC_LOGS', home / 'logs'))
    return home, config, state, logs


def parser():
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument('--config', default=argparse.SUPPRESS)
    shared.add_argument('--state', default=argparse.SUPPRESS)
    shared.add_argument('--json', action='store_true', default=argparse.SUPPRESS)
    p = argparse.ArgumentParser(prog='slot-sync', parents=[shared], description='Synchronize busy-time copies; sources stay read-only')
    p.add_argument('--version', action='version', version='SlotSync ' + __version__)
    sub = p.add_subparsers(dest='command')
    for name in ('home', 'version', 'status', 'doctor', 'demo'):
        sub.add_parser(name, parents=[shared])
    setup = sub.add_parser('setup', aliases=['init', 'setup-config'], parents=[shared])
    setup.add_argument('--no-edit', action='store_true')
    config = sub.add_parser('config', parents=[shared])
    config.add_argument('--edit', action='store_true')
    for name in ('sync', 'preview', 'run'):
        s = sub.add_parser(name, parents=[shared])
        group = s.add_mutually_exclusive_group()
        group.add_argument('--apply', action='store_true')
        group.add_argument('--dry-run', action='store_true')
        s.add_argument('--details', action='store_true')
        s.add_argument('--scheduled', action='store_true', help='Publish applied pass health for the system scheduler')
    auth = sub.add_parser('auth', parents=[shared]).add_subparsers(dest='action', required=True)
    auth.add_parser('status', parents=[shared])
    login = auth.add_parser('login', parents=[shared])
    login.add_argument('--account', required=True)
    login.add_argument('--no-browser', action='store_true')
    cal = sub.add_parser('calendar', parents=[shared]).add_subparsers(dest='action', required=True).add_parser('ensure', parents=[shared])
    cal.add_argument('--account', required=True)
    avail = sub.add_parser('availability', parents=[shared])
    for flag in ('account', 'start', 'end'):
        avail.add_argument('--' + flag, required=True)
    daemon = sub.add_parser('daemon', parents=[shared])
    daemon.add_argument('action', choices=['start', 'stop', 'restart', 'status'])
    return p


def edit(path):
    command = os.environ.get('VISUAL') or os.environ.get('EDITOR') or 'vi'
    require(subprocess.run([command, str(path)]).returncode == 0, 'Editor exited unsuccessfully')


def dispatch(args):
    home, path, state, logs = paths(args)
    command = args.command
    if command in ('home', 'version'):
        return {'home': str(home)} if command == 'home' else {'name': 'SlotSync', 'version': __version__}
    if command in ('setup', 'init', 'setup-config'):
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'w') as f:
                f.write(files('slot_sync').joinpath('example.toml').read_text())
            created = True
        except FileExistsError:
            created = False
        if not args.no_edit and not getattr(args, 'json', False) and sys.stdin.isatty():
            edit(path)
        return {'config': str(path), 'created': created, 'existing_config_preserved': not created}
    if command == 'config':
        if args.edit:
            require(path.is_file(), 'Config missing; run setup')
            edit(path)
        return {'config': str(path)}
    if command == 'status':
        health_dir = os.environ.get('SLOT_SYNC_HEALTH_DIR') or os.environ.get('GALLENDAR_HEALTH_DIR')
        try:
            health = json.loads((Path(health_dir) / 'health.json').read_text()) if health_dir else None
        except (OSError, ValueError):
            health = None
        result = {'name': 'SlotSync', 'version': __version__, 'config': str(path), 'state': str(state), 'health': health}
        if health and health.get('last_success_at'):
            local = instant(health['last_success_at']).astimezone(ZoneInfo('Europe/Warsaw'))
            result['last_success_warsaw'] = local.strftime('%Y-%m-%d %H:%M:%S %Z (UTC%z)')
        return result
    if command == 'daemon':
        require(sys.platform.startswith('linux'), 'Use the installed Linux systemd timer; no Mac background writer is installed')
        action = args.action
        argv = ['systemctl', '--user'] if os.environ.get('SLOT_SYNC_USER_SERVICE') else ['systemctl']
        if action == 'status':
            out = subprocess.run(argv + ['show', 'slot-sync.timer', '-p', 'ActiveState', '-p', 'UnitFileState'], capture_output=True, text=True)
        else:
            op = {'start': ['enable', '--now'], 'stop': ['disable', '--now'], 'restart': ['restart']}[action]
            out = subprocess.run(argv + op + ['slot-sync.timer'], capture_output=True, text=True)
            if action == 'stop' and out.returncode == 0:
                out = subprocess.run(argv + ['stop', 'slot-sync.service'], capture_output=True, text=True)
        require(out.returncode == 0, 'Systemd operation failed; run with the intended service administration permissions')
        return {'action': action, 'service': 'slot-sync.timer', 'state': out.stdout.strip()}
    if command == 'demo':
        from .demo import run
        return run()
    if command in ('sync', 'preview', 'run'):
        apply = command != 'preview' and not args.dry_run and (args.apply or command == 'run')
        require(not args.scheduled or apply, '--scheduled requires an applied synchronization')
        kwargs = dict(apply=apply, scheduled=args.scheduled or command == 'run',
                      health_dir=os.environ.get('SLOT_SYNC_HEALTH_DIR') or os.environ.get('GALLENDAR_HEALTH_DIR'), details=args.details)
        if command != 'run':
            return sync(path, state, logs, **kwargs)
        stop = threading.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
        while not stop.is_set():
            try:
                print(json.dumps(sync(path, state, logs, **kwargs)), flush=True)
            except SyncError as error:
                print('slot-sync: ' + str(error), file=sys.stderr, flush=True)
            interval = Config.load(path).poll_seconds
            stop.wait(interval - time.time() % interval)
        return {'stopped': True}
    cfg = Config.load(path, validate=not (command == 'auth'))
    if command == 'auth':
        if args.action == 'status':
            return oauth.status(cfg)
        return oauth.login(cfg, cfg.account(args.account), http, args.no_browser)
    if command == 'calendar':
        require(cfg.mirror_name, 'Set mirror_calendar_name first')
        a = cfg.account(args.account)
        require(a in cfg.targets(), 'Calendar ensure is allowed only for a route destination')
        api = Google(cfg)
        calendar, created = api.named_calendar(a['name'], cfg.mirror_name, True)
        return {'account': a['name'], 'calendar_id': calendar, 'created': created, 'events_created': 0}
    api = Google(cfg).resolve()
    if command == 'doctor':
        checks, ready = [], True
        for a in cfg.sources():
            role = api.source(a['source'], cfg.window())['accessRole']
            readable = role in ('reader', 'writer', 'writerWithoutPrivateAccess', 'owner')
            checks.append({'account': a['name'], 'source_role': role, 'source_readable': readable})
            ready &= readable
        for a in cfg.targets():
            role = api.clones(a['target'], digest(cfg.namespace))['accessRole']
            writable = role in ('writer', 'writerWithoutPrivateAccess', 'owner')
            checks.append({'account': a['name'], 'target_role': role, 'target_writable': writable})
            ready &= writable
        require(ready, 'Insufficient calendar permissions')
        return {'ready': ready, 'checks': checks, 'google_writes_tested': False, 'account_availability_validated': False}
    if command == 'availability':
        a = cfg.account(args.account)
        start, end = instant(args.start), instant(args.end)
        require(end > start, 'end must be later than start')
        return {'account': a['name'], 'primary_busy': api.availability(a['owner_email'], start, end),
                'source_busy': api.availability(a['source'], start, end) if a['source'] else None,
                'clone_busy': api.availability(a['target'], start, end) if a['target'] else None,
                'account_aggregation_proven': False}
    raise SyncError('Unsupported command')


def main():
    p = parser()
    args = p.parse_args()
    for field in ('config', 'state'):
        if not hasattr(args, field):
            setattr(args, field, None)
    if args.command is None:
        p.print_help()
        return
    try:
        value = dispatch(args)
        print(json.dumps(value, ensure_ascii=False, indent=None if getattr(args, 'json', False) else 2))
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except (SyncError, OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        message = str(error) if isinstance(error, SyncError) else 'Operation failed; inspect configuration and private service diagnostics (values omitted)'
        print('slot-sync: ' + message, file=sys.stderr)
        raise SystemExit(1) from None
