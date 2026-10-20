"""Private atomic files, compatible process locks and durable creation identities."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import uuid
from .config import SyncError


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value, mode=0o600):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, ensure_ascii=False, separators=(',', ':'))
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextmanager
def lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SyncError('Another synchronization or OAuth operation is active; retry later') from None
        yield
    finally:
        os.close(fd)


class State:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
        self.db = sqlite3.connect(path, timeout=2)
        if self.db.execute('PRAGMA user_version').fetchone()[0] > 1:
            self.db.close()
            raise SyncError('State schema is newer than this application; refusing downgrade')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
            CREATE TABLE IF NOT EXISTS identities (
              namespace TEXT NOT NULL, calendar TEXT NOT NULL, logical_key TEXT NOT NULL,
              event_id TEXT NOT NULL, confirmed INTEGER NOT NULL,
              PRIMARY KEY(namespace, calendar, logical_key));
            CREATE TABLE IF NOT EXISTS passes (
              id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, completed_at TEXT,
              outcome TEXT, counts TEXT);
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            PRAGMA user_version=1;
        ''')

    def creation_id(self, namespace, calendar, key):
        row = self.db.execute('SELECT event_id, confirmed FROM identities WHERE namespace=? AND calendar=? AND logical_key=?', (namespace, calendar, key)).fetchone()
        if row and not row[1]:
            return row[0]
        event_id = 'gld' + uuid.uuid4().hex
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO identities VALUES (?,?,?,?,0)', (namespace, calendar, key, event_id))
        return event_id

    def remember(self, namespace, calendar, key, event_id):
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO identities VALUES (?,?,?,?,1)', (namespace, calendar, key, event_id))

    def abandon_cancelled(self, namespace, calendar, key):
        with self.db:
            self.db.execute('DELETE FROM identities WHERE namespace=? AND calendar=? AND logical_key=?', (namespace, calendar, key))

    def adopt(self, namespace, bindings):
        with self.db:
            self.db.executemany('INSERT OR REPLACE INTO identities VALUES (?,?,?,?,1)',
                                [(namespace, calendar, key, event_id) for calendar, key, event_id in bindings])

    def begin(self):
        with self.db:
            return self.db.execute('INSERT INTO passes(started_at) VALUES (?)', (utcnow(),)).lastrowid

    def finish(self, pass_id, outcome, counts=None):
        with self.db:
            self.db.execute('UPDATE passes SET completed_at=?, outcome=?, counts=? WHERE id=?', (utcnow(), outcome, json.dumps(counts), pass_id))

    def close(self):
        self.db.close()
