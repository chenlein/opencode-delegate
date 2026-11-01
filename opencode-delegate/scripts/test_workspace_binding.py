"""Caller PWD versus managed worktree; offline, no real model/network calls."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_delegate as fixture
import opencode_adapter as adapter
import delegate as scanner
from delegate_core import GuardError, PRELUDE


class RuntimeDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='delegate-pwd-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.worktree = self.root / 'worktree'; self.worktree.mkdir()
        self.other = self.root / 'source'; self.other.mkdir()

    def test_stale_caller_pwd_is_rebound_without_mutating_parent(self):
        with patch.dict(os.environ, {'PWD': str(self.other)}):
            env = adapter.runtime_env({}, self.worktree)
            self.assertEqual(env['PWD'], str(self.worktree))
            self.assertEqual(os.environ['PWD'], str(self.other))

    def test_actual_child_preferring_pwd_reads_worktree(self):
        (self.other / 'marker.txt').write_text('WRONG SOURCE')
        (self.worktree / 'marker.txt').write_text('RIGHT WORKTREE')
        with patch.dict(os.environ, {'PWD': str(self.other)}):
            env = adapter.runtime_env({}, self.worktree)
        # Reproduce the upstream v2.2.3 root-selection expression, not a model.
        code = "import os; from pathlib import Path; os.chdir(os.environ.get('PWD') or os.getcwd()); print(Path('marker.txt').read_text())"
        result = subprocess.run([sys.executable, '-c', code], cwd=self.worktree, env=env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'RIGHT WORKTREE')

    def test_parent_path_alias_is_canonicalized(self):
        alias = self.root / 'parent-alias'; alias.symlink_to(self.root, target_is_directory=True)
        env = adapter.runtime_env({}, alias / 'worktree')
        self.assertEqual(env['PWD'], str(self.worktree))

    def test_missing_or_symlink_worktree_rejected(self):
        alias = self.root / 'alias'; alias.symlink_to(self.worktree, target_is_directory=True)
        for path in (self.root / 'missing', alias):
            with self.subTest(path=path), self.assertRaises(GuardError): adapter.runtime_env({}, path)

    def test_existing_environment_restrictions_preserved(self):
        with patch.dict(os.environ, {'GIT_DIR': '/wrong', 'OPENCODE_CONFIG': '/wrong', 'PWD': str(self.other)}):
            env = adapter.runtime_env({'formatter': False}, self.worktree)
        self.assertNotIn('GIT_DIR', env)
        self.assertNotIn('OPENCODE_CONFIG', env)
        self.assertEqual(json.loads(env['OPENCODE_CONFIG_CONTENT']), {'formatter': False})
        self.assertEqual(env['OPENCODE_DISABLE_AUTOUPDATE'], '1')

    def test_shared_file_scanner_includes_untracked_ignored_and_symlink_metadata(self):
        (self.worktree / '.git').mkdir()
        (self.worktree / '.git/internal').write_text('not source')
        (self.worktree / 'ignored').mkdir()
        (self.worktree / 'ignored/artifact.txt').write_text('build artifact')
        (self.worktree / 'untracked.txt').write_text('untracked')
        (self.worktree / 'link').symlink_to(self.other)
        entries, size = scanner.scan_files(self.worktree)
        self.assertEqual(set(entries), {'ignored/artifact.txt', 'untracked.txt', 'link'})
        self.assertEqual(entries['link']['kind'], 'symlink')
        self.assertEqual(size, len('build artifact') + len('untracked'))

    def test_shared_scanner_retains_size_limit_and_managed_snapshot_guard(self):
        (self.worktree / 'large').write_text('too large')
        with patch.object(scanner, 'MAX_BYTES', 2), self.assertRaises(GuardError): scanner.scan_files(self.worktree)
        (self.worktree / '.git').mkdir()
        with self.assertRaises(GuardError): scanner.snapshot(self.worktree)


class PacketDirectoryTests(unittest.TestCase):
    setUp = fixture.RunnerTests.setUp
    tearDown = fixture.RunnerTests.tearDown
    git = fixture.RunnerTests.git
    call = fixture.RunnerTests.call
    init = fixture.RunnerTests.init
    state = fixture.RunnerTests.state
    run_worker = fixture.RunnerTests.run_worker

    def test_handoff_distinguishes_source_provenance_from_execution_paths(self):
        self.init(); self.run_worker()
        packet = json.loads((self.task / 'attempts/001/packet.json').read_text())
        wt = (self.task / 'worktree').resolve()
        self.assertNotEqual(wt, self.repo.resolve())
        self.assertEqual(packet['anchors']['managed_worktree'], str(wt))
        self.assertEqual(packet['anchors']['source_repository'], str(self.repo.resolve()))
        for context in packet['context_index']:
            self.assertEqual(Path(context['worktree_path']), wt / context['path'])
        # Preserve frozen rule provenance rather than silently rewriting it.
        local = [row for row in packet['instruction_manifest'] if row['worktree_path']]
        self.assertTrue(local)
        self.assertTrue(all(str(self.repo) in row['source'] for row in local))
        self.assertIn('provenance, NOT read/edit targets', PRELUDE)


if __name__ == '__main__':
    unittest.main(verbosity=2)
