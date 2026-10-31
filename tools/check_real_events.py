#!/usr/bin/env python3
"""Replay reviewed native CLI captures and explicitly labeled derived faults.

No model, network, task creation or user configuration changes. Raw captures and
private paths are not packaged; the corpus has a separate integrity manifest.
"""
from pathlib import Path
import hashlib
import inspect
import json
import re
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def corpus_files(folder):
    if folder.is_symlink():
        raise ValueError('Symlink event-corpus directory is not allowed')
    manifest_path = folder / 'manifest.json'
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError('Reviewed real-event corpus manifest is missing/unsafe')
    manifest = json.loads(manifest_path.read_text())
    files = [manifest_path]
    for name, digest in manifest['sha256'].items():
        if not re.fullmatch(r'[a-z0-9_-]+\.ndjson', name):
            raise ValueError('Unsafe event-corpus filename')
        path = folder / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Event corpus content changed: ' + name)
        files.append(path)
    for test in manifest['tests']:
        if test['file'] not in manifest['sha256']:
            raise ValueError('Test references an unreviewed event file')
    actual = {p for p in folder.rglob('*') if p.is_file() or p.is_symlink()}
    if actual != set(files):
        raise ValueError('Unexpected/unreviewed event-corpus files')
    for path in files:
        text = path.read_text()
        if any(value in text for value in ['/Users/', '/home/', '/workspace/', '/private/var/folders/', 'providerCall', 'providerResult', 'OPENCODE_CONFIG_CONTENT']):
            raise ValueError('Unreviewed private/raw metadata in public corpus')
    return files


def fixture_files(root=ROOT):
    base = root / 'validation-fixtures'
    folders = sorted(p for p in base.iterdir() if p.is_dir() and re.fullmatch(r'opencode-v[0-9]+', p.name))
    if base / 'opencode-v223' not in folders:
        raise ValueError('Historical reviewed corpus must remain present')
    return [file for folder in folders for file in corpus_files(folder)]


def main():
    files = fixture_files()
    sys.path.insert(0, str(ROOT / 'opencode-delegate/scripts'))
    from delegate_core import GuardError
    from opencode_adapter import parse_events
    rows = []
    for manifest_path in [p for p in files if p.name == 'manifest.json']:
        manifest = json.loads(manifest_path.read_text())
        for test in manifest['tests']:
            path = manifest_path.parent / test['file']
            row = {'name': test['name'], 'origin': test['origin'], 'expected': test['expected'], 'cli_version': manifest['cli_version']}
            try:
                result = parse_events(path, test['task_id'], test.get('expected_session', test['session_id']))
                row['actual'] = result['result']['status']
                row['matched'] = row['actual'] == test['expected']
            except (GuardError, ValueError, KeyError) as exc:
                row.update(actual='reject', matched=test['expected']=='reject', reason=str(exc))
            rows.append(row)
    output = {'result': 'PASS' if all(x['matched'] for x in rows) else 'FAIL',
              'tests': len(rows), 'native_capture_tests': sum(x['origin']=='native_capture' for x in rows),
              'derived_fault_tests': sum(x['origin']!='native_capture' for x in rows),
              'parser_sha256': hashlib.sha256(inspect.getsource(parse_events).encode()).hexdigest(),
              'raw_native_behavior_is_not_inferred_from_fault_fixtures': True, 'results': rows}
    print(json.dumps(output, indent=2))
    return 0 if output['result']=='PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
