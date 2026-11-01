#!/usr/bin/env python3
"""Installer tests use temporary homes only; no OpenCode or model calls."""
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='delegate-install-test-')
        # macOS can return /var/... while the installer returns /private/var/....
        # Compare filesystem identities, not two spellings of the same directory.
        self.home = Path(self.tmp.name).resolve()
        self.target = self.home / '.agents/skills/opencode-delegate'
        self.env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(self.home),
                    "XDG_CONFIG_HOME": str(self.home / ".config"), "CODEX_HOME": str(self.home / ".codex"),
                    "PYTHONDONTWRITEBYTECODE": "1"}

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

    def test_diagnostic_help_does_not_contaminate_release(self):
        release = self.home / 'diagnostic-release'
        shutil.copytree(ROOT, release, ignore=shutil.ignore_patterns('.git', '__pycache__', '.local-results', 'dist'))
        env = dict(self.env)
        env.pop('PYTHONDONTWRITEBYTECODE', None)
        for tool in ('probe_session_permissions.py', 'probe_native_permissions.py',
                     'benchmark_repository.py', 'benchmark_snapshot.py', 'build_release.py'):
            result = subprocess.run([sys.executable, str(release / 'tools' / tool), '--help'],
                                    env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(list((release / 'opencode-delegate').rglob('*.pyc')))

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
        self.assertNotIn(self.target.parent.resolve(), backup.resolve().parents)

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

    def test_a08_alternate_discovery_root_is_not_a_backup_destination(self):
        original = self.old_install().read_bytes()
        result = self.run_install('--replace', '--backup-root', str(self.home / '.codex/skills/backups'))
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertEqual((self.target / 'scripts/delegate.py').read_bytes(), original)

    def test_a08_codex_home_discovery_root_is_protected(self):
        self.old_install()
        self.env['CODEX_HOME'] = str(self.home / 'custom-codex')
        result = self.run_install('--replace', '--backup-root', str(self.home / 'custom-codex/skills/backup'))
        self.assertEqual(result.returncode, 2)

    def test_a08_backup_parent_alias_cannot_enter_discovery_root(self):
        self.old_install()
        scan = self.home / '.codex/skills'; scan.mkdir(parents=True)
        alias = self.home / 'scan-alias'; alias.symlink_to(scan, target_is_directory=True)
        result = self.run_install('--replace', '--backup-root', str(alias / 'backups'))
        self.assertEqual(result.returncode, 2)
        self.assertFalse((scan / 'backups').exists())

    def test_a08_release_alias_cannot_overwrite_package(self):
        release = self.home / 'release'
        shutil.copytree(ROOT, release, ignore=shutil.ignore_patterns('.git', '__pycache__', '.local-results', 'dist'))
        alias = self.home / 'alias'; alias.symlink_to(release, target_is_directory=True)
        original = (release / 'opencode-delegate/SKILL.md').read_bytes()
        result = subprocess.run([sys.executable, str(release / 'install.py'), '--replace', '--target', str(alias / 'opencode-delegate')], env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn('unpacked release', result.stderr)
        self.assertEqual((release / 'opencode-delegate/SKILL.md').read_bytes(), original)

    def test_a08_legal_external_backup_is_supported(self):
        original = self.old_install().read_bytes()
        root = self.home / 'separate-backups'
        result = self.run_install('--replace', '--backup-root', str(root))
        self.assertEqual(result.returncode, 0, result.stderr)
        saved = Path(json.loads(result.stdout)['backup'])
        self.assertIn(root.resolve(), saved.resolve().parents)
        self.assertEqual((saved / 'scripts/delegate.py').read_bytes(), original)

    def test_a08_legal_backup_parent_alias_preserves_files(self):
        original = self.old_install().read_bytes()
        real = self.home / 'separate-backups'; real.mkdir()
        alias = self.home / 'backup-alias'; alias.symlink_to(real, target_is_directory=True)
        result = self.run_install('--replace', '--backup-root', str(alias))
        self.assertEqual(result.returncode, 0, result.stderr)
        saved = Path(json.loads(result.stdout)['backup'])
        self.assertIn(real.resolve(), saved.resolve().parents)
        self.assertEqual((saved / 'scripts/delegate.py').read_bytes(), original)
        self.assertEqual((self.target / 'scripts/delegate.py').read_bytes(), (ROOT / 'opencode-delegate/scripts/delegate.py').read_bytes())
        self.assertTrue(alias.is_symlink())

    def test_a08_install_cannot_replace_ancestor_of_release(self):
        outer = self.home / 'opencode-delegate'
        release = outer / 'release'
        shutil.copytree(ROOT, release, ignore=shutil.ignore_patterns('.git', '__pycache__', '.local-results', 'dist'))
        result = subprocess.run([sys.executable, str(release / 'install.py'), '--replace', '--target', str(outer)], env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertTrue((release / 'MANIFEST.json').is_file())


if __name__ == '__main__':
    unittest.main(verbosity=2)
