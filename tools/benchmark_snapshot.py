#!/usr/bin/env python3
"""Synthetic snapshot measurement; not a user-project/model benchmark."""
import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'opencode-delegate/scripts'))
import delegate as d


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--files', type=int, default=1000)
    p.add_argument('--bytes', type=int, default=4096)
    p.add_argument('--repeats', type=int, default=3)
    a = p.parse_args()
    if not (1 <= a.files <= 20000 and 1 <= a.bytes <= 65536 and 1 <= a.repeats <= 10):
        p.error('Use 1..20000 files, 1..65536 bytes/file, 1..10 repeats')
    with tempfile.TemporaryDirectory(prefix='delegate-benchmark-') as tmp:
        root = Path(tmp); repo = root / 'repo'; repo.mkdir()
        def git(*cmd):
            subprocess.run(['git','-C',str(repo),*cmd], check=True, capture_output=True)
        git('init','-q'); git('config','user.name','Benchmark'); git('config','user.email','benchmark@example.test')
        git('-c','commit.gpgsign=false','commit','--allow-empty','-qm','baseline')
        wt = root / 'worktree'; git('worktree','add','--detach',str(wt),'HEAD')
        for i in range(a.files):
            (wt / f'file-{i:06d}.txt').write_bytes(b'x' * a.bytes)
        d.SCAN_METRICS.clear()
        for _ in range(a.repeats):
            d.snapshot(wt)
        print(json.dumps({'kind':'synthetic_snapshot_only','platform':platform.platform(),'python':platform.python_version(), 'files':a.files,'bytes_per_file':a.bytes,'samples':d.SCAN_METRICS}, indent=2))


if __name__ == '__main__':
    main()
