#!/usr/bin/env python3
"""Read-only real-repository scan measurement, not a model/runtime benchmark.

Uses the production scanner and its unchanged size/file limits. No checkout,
worktree registration, optional Git lock, build, test or model task is started.
Only aggregate results are printed; source files and private names stay local.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import resource
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'opencode-delegate/scripts'))
import delegate as d


def git(root, *args):
    p = subprocess.run(['git', '--no-optional-locks', '-c', 'core.fsmonitor=false',
                        '-c', 'core.untrackedCache=false', '-C', str(root), *args],
                       capture_output=True, timeout=120)
    if p.returncode:
        raise RuntimeError('Read-only Git identity query failed')
    return p.stdout


def identity(root):
    status = git(root, 'status', '--porcelain=v1', '--untracked-files=all')
    return {'head': git(root, 'rev-parse', 'HEAD').decode().strip(),
            'index_sha256': hashlib.sha256(git(root, 'ls-files', '--stage', '-z') + git(root, 'ls-files', '-v', '-z')).hexdigest(),
            'status_sha256': hashlib.sha256(status).hexdigest(),
            'dirty_entries': len(status.splitlines())}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo', required=True)
    p.add_argument('--scan-root', help='Explicit subtree within repo; never presented as a whole-repository scan')
    p.add_argument('--repeats', type=int, default=2)
    args = p.parse_args()
    if not 1 <= args.repeats <= 3:
        p.error('Use 1..3 repeats')
    root = Path(args.repo).expanduser().resolve()
    if Path(git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve() != root:
        p.error('repo must be the exact Git root')
    scan_root = Path(args.scan_root).expanduser().resolve() if args.scan_root else root
    if scan_root != root and root not in scan_root.parents:
        p.error('scan-root must stay within the authorized repository')
    relative = scan_root.relative_to(root).as_posix()
    before = identity(root)
    samples, prior = [], None
    started_all = time.monotonic()
    result = {'kind': 'real_repository_file_scan_only', 'scan_root_relative': relative,
              'whole_repository': scan_root == root, 'platform': platform.platform(),
              'python': platform.python_version(), 'limits': {'files': d.MAX_FILES, 'bytes': d.MAX_BYTES},
              'identity_before': before, 'samples': samples, 'model_invoked': False,
              'repository_writes_requested': False}
    exit_code = 0
    try:
        # Enumerate classifications through read-only Git, including ignored files.
        scope = [] if scan_root == root else ['--', relative + '/']
        ignored = git(root, 'ls-files', '--others', '--ignored', '--exclude-standard', '-z', *scope).split(b'\0')
        untracked = git(root, 'ls-files', '--others', '--exclude-standard', '-z', *scope).split(b'\0')
        result['ignored_file_count'] = sum(bool(x) for x in ignored)
        result['untracked_file_count'] = sum(bool(x) for x in untracked)
        for _ in range(args.repeats):
            started = time.monotonic()
            entries, size = d.scan_files(scan_root)
            scan_seconds = time.monotonic() - started
            fingerprint = d.digest(entries)
            result.setdefault('snapshots_stable', True)
            if prior is not None and fingerprint != prior:
                result['snapshots_stable'] = False
            prior = fingerprint
            unsafe = sum(d.secret_path(path) or value['kind'] != 'file' for path, value in entries.items())
            samples.append({'files': len(entries), 'bytes': size, 'scan_seconds': round(scan_seconds, 6),
                            'file_manifest_sha256': fingerprint, 'unsafe_for_delegate_entries': unsafe,
                            'peak_rss_raw': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                            'peak_rss_unit': 'bytes' if sys.platform == 'darwin' else 'KiB'})
    except (d.GuardError, OSError, ValueError, RuntimeError) as exc:
        result['stopped'] = {'type': type(exc).__name__, 'reason': str(exc)}
        exit_code = 2
    result['identity_after'] = identity(root)
    result['elapsed_seconds'] = round(time.monotonic() - started_all, 6)
    result['peak_rss_raw'] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result['peak_rss_unit'] = 'bytes' if sys.platform == 'darwin' else 'KiB'
    result['git_identity_unchanged'] = result['identity_after'] == before
    result['result'] = 'PASS_MEASUREMENT_ONLY' if not exit_code and result['git_identity_unchanged'] else 'PARTIAL'
    result['scope_limit'] = 'Shared production file scanner only; no managed Git snapshot, independent-check lifecycle or end-to-end model throughput qualification.'
    print(json.dumps(result, indent=2))
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
