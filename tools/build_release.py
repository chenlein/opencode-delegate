#!/usr/bin/env python3
"""Build/check a stdlib-only release; never include caches or runtime task logs."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile
from check_real_events import fixture_files
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'opencode-delegate/scripts'))
from delegate_core import VERSION


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', help='New ZIP path; never overwrite')
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    reviewed_events = fixture_files(ROOT)  # Integrity/packaging only; no tests are executed here.
    files = sorted(p for p in (ROOT / 'opencode-delegate').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc') + [ROOT / 'install.py']
    if any(p.is_symlink() for p in files):
        raise ValueError('Symlink in release inputs')
    manifest = {'version':VERSION, 'sha256':{p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    path = ROOT / 'MANIFEST.json'
    if args.check:
        if json.loads(path.read_text()) != manifest:
            raise ValueError('Stale MANIFEST.json; run tools/build_release.py')
    else:
        path.write_text(json.dumps(manifest, indent=2) + '\n')
    if args.output:
        with zipfile.ZipFile(Path(args.output).expanduser(), 'x', zipfile.ZIP_DEFLATED) as z:
            included = files + [path, ROOT / 'README.md', ROOT / 'CHANGELOG.md']
            included += [p for folder in ('docs','tools') for p in sorted((ROOT / folder).glob('*')) if p.is_file() and p.suffix != '.pyc']
            included += reviewed_events
            for p in included:
                z.write(p, f'opencode-delegate-{VERSION}/' + p.relative_to(ROOT).as_posix())
    print(json.dumps({'version':VERSION, 'files':len(files), 'manifest_checked':args.check}))


if __name__ == '__main__':
    main()
