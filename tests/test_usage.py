import json
import tempfile
import time
import unittest
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from slot_sync import usage


def write_record(args):
    directory, number = args
    usage.append(directory, 'events.jsonl', {'epoch_seconds': int(time.time()), 'number': number})


class UsageTests(unittest.TestCase):
    def test_processes_keep_complete_records(self):
        with tempfile.TemporaryDirectory() as directory:
            with ProcessPoolExecutor(max_workers=4) as pool:
                list(pool.map(write_record, [(directory, i) for i in range(40)]))
            records = [json.loads(line) for line in (Path(directory) / 'events.jsonl').read_text().splitlines()]
            self.assertEqual({r['number'] for r in records}, set(range(40)))

    def test_age_size_and_metadata_privacy(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory) / 'events.jsonl'
            current.write_text('{"epoch_seconds":1,"text":"private-old"}\n')
            usage.event(directory, 'sync', 'success', {'created': 2, 'title': 'private-new'})
            text = current.read_text()
            self.assertNotIn('private', text)
            self.assertEqual(json.loads(text)['fields'], {'created': 2})
            record = {'epoch_seconds': int(time.time()), 'padding': 'x' * 3900}
            line = json.dumps(record) + '\n'
            for _ in range(7):
                current.write_text(line * ((2 * 1024 * 1024) // len(line)))
                usage.append(directory, 'events.jsonl', record)
            files = list(Path(directory).glob('events.jsonl*'))
            self.assertEqual(len(files), 5)
            self.assertLessEqual(sum(p.stat().st_size for p in files), 10 * 1024 * 1024)

    def test_usage_is_optional_but_audit_failure_propagates(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'file'
            target.write_text('preserve')
            usage.event(target, 'sync', 'success')
            with self.assertRaises(OSError):
                usage.append(target, 'audit.jsonl', {'event': 'prewrite'})
            self.assertEqual(target.read_text(), 'preserve')
