"""One-pass orchestration, durable recovery and private audit logging."""
from contextlib import ExitStack
from dataclasses import asdict
import json
from pathlib import Path
from . import health, usage
import time
import uuid
from .config import Config, SyncError
from .google import Google
from .planner import plan
from .storage import State, lock, utcnow


def audit(directory, kind, data):
    usage.append(directory, 'audit.jsonl', {'timestamp': utcnow(), 'epoch_seconds': int(time.time()),
                                          'event': kind, 'data': data}, maximum=2 * 1024 * 1024)


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
    operation_id, started = uuid.uuid4().hex, time.monotonic()
    usage.event(logs_dir, 'sync_pass', 'started', {'apply': apply, 'scheduled': scheduled}, operation_id)
    verified = 0
    def record_operation(kind, value):
        nonlocal verified
        audit(logs_dir, kind, value)
        if kind == "operation_verified":
            verified += 1
            usage.event(logs_dir, "calendar_write", "success", {"mode": value["kind"], "operations": 1}, operation_id)
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
                execute(api, planned, state, record_operation)
                completion[:] = ['success', planned.counts]
            result = {'applied': apply, 'namespace': planned.namespace, 'changes': planned.counts}
            if details:
                result['actions'] = [asdict(a) for a in planned.actions]
        if apply and scheduled and health_dir:
            health.complete(health_dir, cfg.poll_seconds)
        usage.event(logs_dir, 'sync_pass', 'success', {**planned.counts, 'apply': apply, 'scheduled': scheduled},
                    operation_id, round((time.monotonic() - started) * 1000))
        return result
    except Exception as error:
        usage.event(logs_dir, 'sync_pass', 'partial' if verified else 'error', {'apply': apply, 'operations': verified, 'error_code': 'sync_failed'},
                    operation_id, round((time.monotonic() - started) * 1000))
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
