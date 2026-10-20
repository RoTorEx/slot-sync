"""One-pass orchestration, durable recovery and private audit logging."""
from contextlib import ExitStack
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from . import health
from .config import Config, SyncError
from .google import Google
from .planner import plan
from .storage import State, lock, utcnow


def audit(directory, kind, data):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    path = directory / (datetime.now(timezone.utc).date().isoformat() + '.jsonl')
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, 'a') as f:
        f.write(json.dumps({'timestamp': utcnow(), 'event': kind, 'data': data}, ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())


def execute(api, planned, state, record=lambda *_args: None):
    for a in planned.actions:
        record('operation_started', {'kind': a.kind, 'target': a.target, 'id': a.event_id})
        if a.kind == 'create':
            api.create(a.target, a.busy, planned.namespace, state)
        elif a.kind == 'update':
            api.update(a.target, a.event_id, a.busy, planned.namespace)
            state.remember(planned.namespace, a.target, a.busy.key, a.event_id)
        else:
            api.delete(a.target, a.event_id, planned.namespace)
        record('operation_verified', {'kind': a.kind, 'target': a.target, 'id': a.event_id})


def sync(config_path, state_path, logs_dir, apply=False, scheduled=False, health_dir=None, details=False):
    cfg, state, pass_id = None, None, None
    try:
        with ExitStack() as stack:
            if apply:
                # Same canonical path and suffix as Rust: prevents overlap at cutover.
                stack.enter_context(lock(Path(config_path).resolve().with_suffix('.lock')))
                stack.enter_context(lock(Path(state_path).with_suffix('.lock')))
                state = State(state_path)
                stack.callback(state.close)
                pass_id = state.begin()
                completion = ["interrupted", None]
                stack.callback(lambda: state.finish(pass_id, *completion))
            cfg = Config.load(config_path)
            api = Google(cfg).resolve()
            planned = plan(api, cfg, cfg.window())
            # Persist the complete plan before any write; logging failure is fatal.
            audit(logs_dir, 'plan', {'namespace': planned.namespace, 'changes': planned.counts,
                                   'applied': apply, 'actions': [asdict(a) for a in planned.actions]})
            if apply:
                state.adopt(planned.namespace, planned.bindings)
                execute(api, planned, state, lambda kind, value: audit(logs_dir, kind, value))
                completion[:] = ['success', planned.counts]
            result = {'applied': apply, 'namespace': planned.namespace, 'changes': planned.counts}
            if details:
                result['actions'] = [asdict(a) for a in planned.actions]
        if apply and scheduled and health_dir:
            health.complete(health_dir, cfg.poll_seconds)
        return result
    except Exception as error:
        if apply and scheduled and health_dir:
            # The last successful pass never advances on failure, including invalid config.
            health.complete(health_dir, cfg.poll_seconds if cfg else configured_interval(config_path, health_dir), error)
        raise


def configured_interval(config_path, health_dir):
    try:
        return Config.load(config_path, validate=False).poll_seconds
    except Exception:
        try:
            value = json.loads((Path(health_dir) / 'health.json').read_text())['poll_seconds']
            return value if type(value) is int and value > 0 else 1800
        except Exception:
            return 1800
