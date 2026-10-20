"""Schema-v1 health compatible with the existing Telegram monitor."""
import json
from pathlib import Path
from . import __version__
from .oauth import ReauthorizationRequired
from .storage import atomic_json, utcnow


def complete(directory, poll_seconds, error=None):
    directory = Path(directory)
    path = directory / 'health.json'
    now = utcnow()
    try:
        old = json.loads(path.read_text())
        if old.get('schema_version') != 1:
            old = {}
    except (OSError, ValueError, AttributeError):
        old = {}
    value = {'schema_version': 1, 'version': __version__, 'started_at': old.get('started_at') or now,
             'poll_seconds': poll_seconds, 'last_pass_at': now,
             'last_success_at': old.get('last_success_at') if error else now,
             'error_kind': ('reauth_required' if isinstance(error, ReauthorizationRequired) else 'sync_failed') if error else None,
             'account': error.account if isinstance(error, ReauthorizationRequired) else None}
    atomic_json(path, value, 0o644)
    return value
