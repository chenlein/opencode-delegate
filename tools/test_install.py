#!/usr/bin/env python3
"""Installer tests use temporary homes only; no OpenCode or model calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='delegate-install-test-')
        self.home = Path(self.tmp.name)
        self.target = self.home / '.agents/skills/opencode-delegate'
        self.env = dict(os.environ, HOME=str(self.home), PYTHONDONTWRITEBYTECODE='1')

    def tearDown(self):
        self.tmp.cleanup()

    def run_install(self, *args):
        return subprocess.run([sys.executable, str(ROOT / 'install.py'), *args], env=self.env, capture_output=True, text=True, timeout=20)

    def old_install(self):
        p = self.target / 'scripts/delegate.py'
        p.parent.mkdir(parents=True)
        p.write_text('VERSION = "2.0.0"\n# fixture, not a complete runner\n')
        return p

    def old_task(self):
        p = self.home / '.local/state/opencode-delegate/project/task/state.json'
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({'runner_version':'2.0.0', 'status':'OUTCOME_UNKNOWN'}))
        return p

    def test_dry_run_is_non_mutating(self):
        result = self.run_install('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.target.exists())

    def test_fresh_install_and_manifest_content(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.target / 'scripts/delegate.py').read_bytes(), (ROOT / 'opencode-delegate/scripts/delegate.py').read_bytes())

    def test_existing_install_requires_explicit_replace(self):
        p = self.old_install(); before = p.read_bytes()
        self.assertEqual(self.run_install().returncode, 2)
        self.assertEqual(p.read_bytes(), before)

    def test_replace_preserves_old_copy_outside_scan_directory(self):
        p = self.old_install(); before = p.read_bytes()
        result = self.run_install('--replace')
        self.assertEqual(result.returncode, 0, result.stderr)
        backup = Path(json.loads(result.stdout)['backup'])
        self.assertEqual((backup / 'scripts/delegate.py').read_bytes(), before)
        self.assertNotIn(self.target.parent, backup.parents)

    def test_ambiguous_install_locations_require_target(self):
        self.old_install()
        (self.home / '.codex/skills/opencode-delegate').mkdir(parents=True)
        self.assertEqual(self.run_install('--dry-run').returncode, 2)

    def test_active_legacy_task_blocks_unacknowledged_upgrade(self):
        self.old_install(); task = self.old_task(); before = task.read_bytes()
        self.assertEqual(self.run_install('--replace').returncode, 2)
        self.assertEqual(task.read_bytes(), before)

    def test_active_legacy_task_keeps_pinned_runner_and_state(self):
        old = self.old_install().read_bytes(); task = self.old_task(); before = task.read_bytes()
        result = self.run_install('--replace', '--preserve-legacy-runner')
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(Path(data['legacy_runner']).read_bytes(), old)
        self.assertEqual(task.read_bytes(), before)
        self.assertFalse(data['task_state_changed'])

    def test_symlink_install_target_is_rejected(self):
        real = self.home / 'other'; real.mkdir()
        self.target.parent.mkdir(parents=True)
        self.target.symlink_to(real, target_is_directory=True)
        self.assertEqual(self.run_install('--replace').returncode, 2)
        self.assertTrue(self.target.is_symlink())


if __name__ == '__main__':
    unittest.main(verbosity=2)
