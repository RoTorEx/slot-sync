"""Small local metadata log; mandatory write audit retains its fail-closed contract."""
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid
from . import __version__

RUN_ID = uuid.uuid4().hex
_warned = False


def append(directory, name, record, maximum=4096):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.is_symlink():
        raise OSError('Log directory must not be a symlink')
    directory.chmod(0o700)
    line = (json.dumps(record, ensure_ascii=True, separators=(',', ':')) + '\n').encode()
    if len(line) > maximum:
        raise OSError('Log record exceeds its size limit')
    current = directory / name
    paths = [current] + [directory / f'{name}.{i}' for i in range(1, 5)]
    lock_path = directory / f'.{name}.lock'
    for path in paths + [lock_path]:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise OSError('Invalid log destination')
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(fd, 'a') as lock:
        deadline = time.monotonic() + .1
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.002)
        now = int(time.time())
        marker = directory / f'.{name}.retention'
        if marker.is_symlink():
            raise OSError('Invalid retention marker')
        try:
            last = int(marker.read_text())
        except (OSError, ValueError):
            last = 0
        if now // 86400 != last // 86400:
            for path in paths:
                if not path.exists():
                    continue
                kept = []
                for old in path.read_text().splitlines():
                    try:
                        value = json.loads(old)
                        if value.get('epoch_seconds', 0) >= now - 90 * 86400:
                            kept.append(old)
                    except ValueError:
                        continue
                temp = directory / f'.{name}.tmp'
                if temp.is_symlink():
                    raise OSError('Invalid retention temporary file')
                fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, 'w') as stream:
                    stream.write('\n'.join(kept) + ('\n' if kept else ''))
                    stream.flush()
                    os.fsync(stream.fileno())
                temp.replace(path)
            marker.write_text(str(now))
            marker.chmod(0o600)
        if current.exists() and current.stat().st_size + len(line) > 2 * 1024 * 1024:
            paths[-1].unlink(missing_ok=True)
            for index in range(3, -1, -1):
                if paths[index].exists():
                    paths[index].replace(paths[index + 1])
        fd = os.open(current, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(fd, 'ab') as stream:
            stream.write(line)
            stream.flush()
            os.fsync(stream.fileno())


def event(directory, action, result, fields=None, operation_id=None, duration_ms=None):
    global _warned
    allowed = {'created', 'updated', 'deleted', 'unchanged', 'create', 'update', 'delete',
               'apply', 'scheduled', 'error_code', 'mode', 'changes', 'operations'}
    safe = {key: value for key, value in (fields or {}).items() if key in allowed and
            (isinstance(value, (int, float, bool)) or
             (isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', value)))}
    record = dict(schema_version=1, timestamp=datetime.now(timezone.utc).isoformat(),
                  epoch_seconds=int(time.time()), app='slot-sync', app_version=__version__,
                  run_id=RUN_ID, operation_id=operation_id, action=action, result=result,
                  duration_ms=duration_ms, fields=safe)
    try:
        append(directory, 'events.jsonl', record)
    except (OSError, ValueError):
        if not _warned:
            print('slot-sync: usage logging unavailable; mandatory audit remains required', file=sys.stderr)
            _warned = True
