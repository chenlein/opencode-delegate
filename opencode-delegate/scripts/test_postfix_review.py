#!/usr/bin/env python3
"""Post-fix review: cross-stage failures; no live OpenCode/model/network calls."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_delegate as fixture
import test_lifecycle_fixes as lifecycle_tests

d = fixture.d


class PostfixReviewTests(unittest.TestCase):
    setUp = fixture.RunnerTests.setUp
    tearDown = fixture.RunnerTests.tearDown
    git = fixture.RunnerTests.git
    call = fixture.RunnerTests.call
    init = fixture.RunnerTests.init
    state = fixture.RunnerTests.state
    run_worker = fixture.RunnerTests.run_worker
    check_command = fixture.RunnerTests.check_command
    verify = fixture.RunnerTests.verify
    review_file = fixture.RunnerTests.review_file
    recover = lifecycle_tests.LifecycleTests.recover
    accept = lifecycle_tests.LifecycleTests.accept
    export = lifecycle_tests.LifecycleTests.export

    def test_missing_verifier_preserves_failure_handoff(self):
        self.check_command("print('pass')")
        self.init(); self.run_worker()
        popen = subprocess.Popen
        def missing(argv, *args, **kwargs):
            if argv[:2] == [sys.executable, '-c']:
                raise FileNotFoundError('injected missing verifier executable')
            return popen(argv, *args, **kwargs)
        with patch.object(d.subprocess, 'Popen', side_effect=missing):
            self.verify(expect=5)
        self.assertEqual(self.state()['status'], 'NEEDS_FIX')
        self.call('failure', '--task', str(self.task), '--include-details', expect=0)
        packet = json.loads(self.last_out)
        check = packet['checks'][0]
        self.assertEqual(check['exit_code'], 127)
        self.assertEqual(check['reason'], 'spawn_error')
        self.assertTrue(all(len(value) == 64 for value in check['log_hashes'].values()))
        feedback = self.root / 'feedback.md'
        feedback.write_text('Verifier executable was unavailable; do not change scope or acceptance.')
        self.run_worker(extra=('--feedback', str(feedback)))
        sent = json.loads((self.task / 'attempts/002/packet.json').read_text())
        self.assertEqual(sent['failure_packet']['checks'][0]['reason'], 'spawn_error')

    def test_missing_worker_records_complete_execution_metadata(self):
        self.init()
        # Always exercise a parent-path alias, including on Linux. The adapter
        # resolves the executable, so fault injection must compare identity.
        alias = self.root / 'worker-parent-alias'
        alias.symlink_to(self.root, target_is_directory=True)
        self.binary = alias / self.binary.name
        popen = subprocess.Popen
        def missing(argv, *args, **kwargs):
            if len(argv) > 1 and Path(argv[0]).resolve() == self.binary.resolve() and argv[1] == 'run' and '--format' in argv:
                raise PermissionError('injected worker launch permission failure')
            return popen(argv, *args, **kwargs)
        with patch.object(d.subprocess, 'Popen', side_effect=missing):
            self.run_worker(expect=4)
        self.assertEqual(self.state()['status'], 'EXECUTION_FAILED')
        path = self.task / 'attempts/001/execution.json'
        result = json.loads(path.read_text())
        self.assertEqual(result['reason'], 'spawn_error')
        self.assertGreaterEqual(result['elapsed_seconds'], 0)
        self.assertEqual(result['stdout_sha256'], d.file_hash(path.parent / 'events.ndjson'))
        self.assertEqual(result['stderr_sha256'], d.file_hash(path.parent / 'stderr.log'))
        self.assertEqual(self.state()['attempts'], 1)

    def test_new_global_override_after_verification_blocks_acceptance(self):
        import os
        self.init(); self.run_worker(); self.verify()
        rule = Path(os.environ['CODEX_HOME']) / 'AGENTS.override.md'
        rule.parent.mkdir(parents=True, exist_ok=True)
        rule.write_text('New policy after verification')
        self.call('review', '--task', str(self.task), '--review', str(self.review_file()), expect=3)
        self.assertEqual(self.state()['status'], 'REVIEW_REQUIRED')
        self.assertIn('New ambient instruction', self.last_err)

    def test_report_write_failure_preserves_legal_verification_artifacts(self):
        self.contract['verification_artifacts'] = ['cache/']
        self.check_command("from pathlib import Path; Path('cache').mkdir(); Path('cache/out').write_text('legal')")
        self.init(); self.run_worker()
        original = d.atomic_json
        def fail_report(path, value):
            if path.name == 'verification.json':
                raise OSError('injected report write failure')
            return original(path, value)
        with patch.object(d, 'atomic_json', side_effect=fail_report):
            self.verify(expect=2)
        self.assertEqual(self.state()['status'], 'VERIFYING')
        self.recover()
        self.assertEqual(self.state()['status'], 'VERIFY_RETRY_READY')
        self.assertEqual(self.state()['operation']['phase'], 'verify')
        self.assertEqual((self.task / 'worktree/cache/out').read_text(), 'legal')
        self.assertIsNone(self.state()['verification'])

    def test_postcheck_state_write_failure_cannot_launder_source_changes(self):
        self.check_command("from pathlib import Path; Path('allowed.txt').write_text('verifier mutation')")
        self.init(); self.run_worker()
        original = d.save
        def fail_checkpoint(task, state, cp=None):
            if state.get('operation', {}).get('stage') == 'checking':
                raise OSError('injected postcheck commit failure')
            return original(task, state, cp)
        with patch.object(d, 'save', side_effect=fail_checkpoint):
            self.verify(expect=2)
        self.recover(expect=3)
        self.assertEqual(self.state()['status'], 'VERIFICATION_MUTATED_SOURCE')
        self.assertIn('Verification modified source: allowed.txt', self.state()['operation']['errors'])

    def test_partial_cleanup_keeps_registration_and_other_source_untouched(self):
        self.accept(); delivery = self.export()
        before = delivery.read_bytes()
        original = d.git
        wt = self.task / 'worktree'
        def interrupted(repo, *args, **kwargs):
            if args[:2] == ('worktree', 'remove'):
                # Remove ONLY this test's exported temporary worktree; leave its
                # Git registration to model a partial remove, never the source.
                shutil.rmtree(wt)
                raise d.GuardError('injected partial git remove')
            return original(repo, *args, **kwargs)
        with patch.object(d, 'git', side_effect=interrupted):
            self.call('cleanup', '--task', str(self.task), '--confirm', expect=2)
        self.assertEqual(self.state()['status'], 'CLEANING')
        self.call('cleanup', '--task', str(self.task), '--confirm', expect=3)
        self.assertIn('Git registration remains', self.last_err)
        self.assertEqual(delivery.read_bytes(), before)
        self.assertEqual(self.git('status', '--porcelain'), b'')
        self.assertEqual((self.repo / 'allowed.txt').read_text(), 'original\n')

    def test_final_empty_message_cannot_borrow_previous_result(self):
        result = {'schema_version':1, 'task_id':'t1', 'status':'complete', 'summary':'earlier', 'claims':[], 'tests_run':[], 'risks':[]}
        text = 'BEGIN_DELEGATE_RESULT' + json.dumps(result) + 'END_DELEGATE_RESULT'
        def event(kind, mid, **fields):
            return {'type':kind, 'sessionID':'ses_test', 'part':{'messageID':mid, **fields}}
        sequence = [event('text', 'm1', text=text), event('step_finish', 'm1', reason='stop'),
                    event('step_start', 'm2'), event('step_finish', 'm2', reason='stop')]
        path = self.root / 'events.ndjson'
        path.write_text('\n'.join(json.dumps(e) for e in sequence))
        with self.assertRaises(d.GuardError):
            d.parse_events(path, 't1', None)
        sequence.insert(-1, event('text', 'm2', text=text.replace('earlier','final')))
        path.write_text('\n'.join(json.dumps(e) for e in sequence))
        parsed = d.parse_events(path, 't1', None)
        self.assertEqual(parsed['final_message_id'], 'm2')
        self.assertEqual(parsed['result']['summary'], 'final')

    def test_status_during_verification_exposes_committed_phase_without_scanning(self):
        self.init()
        _, state, _, cp = d.load(self.task)
        d.begin_operation(self.task, state, cp, 'verify', 'VERIFYING')
        with d.locked(self.task):
            self.call('status', '--task', str(self.task), '--check-worktree', expect=0)
        value = json.loads(self.last_out)
        self.assertEqual(value['status'], 'VERIFYING')
        self.assertEqual(value['operation']['phase'], 'verify')
        self.assertIsNone(value['worktree_matches_checkpoint'])
        self.assertIn('writer active', value['scan_skipped'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
