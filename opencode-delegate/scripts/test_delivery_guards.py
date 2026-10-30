#!/usr/bin/env python3
"""Reconcile reviewed rc.4 delivery with the already-published rc.4 baseline.

Only temporary repositories, fake OpenCode and authorized local checks are used.
No model/network calls; existing remote test cases and state names are preserved.
"""
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import test_delegate as old
import test_lifecycle_fixes as lifecycle_tests

d = old.d


class DeliveryGuardTests(unittest.TestCase):
    setUp = old.RunnerTests.setUp
    tearDown = old.RunnerTests.tearDown
    git = old.RunnerTests.git
    call = old.RunnerTests.call
    init = old.RunnerTests.init
    state = old.RunnerTests.state
    run_worker = old.RunnerTests.run_worker
    check_command = old.RunnerTests.check_command
    verify = old.RunnerTests.verify
    review_file = old.RunnerTests.review_file
    recover = lifecycle_tests.LifecycleTests.recover

    def interrupt_verification(self):
        self.check_command("print('PASS')", ['PASS'])
        self.init()
        self.run_worker('edit')
        original = d.atomic_json
        def fail(path, value):
            if path.name == 'verification.json':
                raise OSError('injected verification report commit failure')
            return original(path, value)
        with patch.object(d, 'atomic_json', side_effect=fail):
            self.verify(expect=2)
        self.assertEqual(self.state()['status'], 'VERIFYING')

    def interrupt_execution_commit(self):
        self.contract.update(max_execution_seconds=10, timeout_seconds=2)
        self.init()
        original = d.save
        def fail(task, state, cp=None):
            if state.get('operation', {}).get('stage') == 'finished':
                raise OSError('injected final execution commit failure')
            return original(task, state, cp)
        with patch.object(d, 'save', side_effect=fail):
            self.run_worker(expect=2)
        self.assertEqual(self.state()['status'], 'RUNNING')
        self.assertEqual(self.state()['total_execution_seconds'], 2)

    def test_completed_result_hash_is_checked_before_first_verify(self):
        self.init()
        self.run_worker('edit')
        path = self.task / 'attempts/001/worker-result.json'
        path.write_text(path.read_text() + '\n')
        self.verify(expect=3)
        self.assertIn('Completed worker result changed', self.last_err)
        self.assertEqual(self.state()['status'], 'AWAITING_VERIFY')
        self.assertFalse((self.task / 'verification').exists())

    def test_completed_result_drift_blocks_verifier_recovery(self):
        self.interrupt_verification()
        path = self.task / 'attempts/001/worker-result.json'
        path.write_text(path.read_text() + '\n')
        before = (self.task / 'state.json').read_bytes()
        self.recover(expect=3)
        self.assertIn('Completed worker result changed', self.last_err)
        self.assertEqual((self.task / 'state.json').read_bytes(), before)

    def test_new_rule_blocks_verifier_recovery(self):
        self.interrupt_verification()
        rule = Path.home() / '.codex/AGENTS.override.md'
        rule.parent.mkdir(parents=True, exist_ok=True)
        rule.write_text('New local instruction; must not be silently adopted.\n')
        before = (self.task / 'state.json').read_bytes()
        self.recover(expect=3)
        self.assertEqual((self.task / 'state.json').read_bytes(), before)

    def test_old_task_without_completion_binding_is_not_adopted(self):
        self.init()
        self.run_worker('edit')
        _, state, _, _ = d.load(self.task)
        state.pop('worker_completion')
        d.save(self.task, state)
        self.verify(expect=3)
        self.assertIn('original runner', self.last_err)

    def test_repeated_frozen_verify_timeouts_keep_last_worker_attempt(self):
        self.contract['max_attempts'] = 1
        self.contract['verification_artifacts'] = ['cache/']
        verifier = self.repo / 'verify_fixture.py'
        verifier.write_text("from pathlib import Path\nimport time\np=Path('cache/attempt')\n"
                            "n=int(p.read_text()) if p.exists() else 0\n"
                            "p.parent.mkdir(exist_ok=True)\np.write_text(str(n+1))\n"
                            "if n < 2: time.sleep(3)\n"
                            "assert Path('allowed.txt').read_text() == 'fixed\\n'\nprint('PASS')\n")
        self.git('add', 'verify_fixture.py')
        self.git('commit', '-qm', 'freeze verification fixture')
        self.contract['verification_sources'] = ['verify_fixture.py']
        self.contract['checks'] = [{'id': 'C1', 'argv': ['{python}', '-S', 'verify_fixture.py'],
                                    'criterion_ids': ['A1'], 'output_contains': ['PASS'], 'timeout_seconds': 1}]
        self.init()
        self.run_worker('edit')
        original = self.state()
        for _ in range(2):
            self.verify(expect=5)
            self.recover()
            self.assertEqual(self.state()['status'], 'VERIFY_RETRY_READY')
            self.assertEqual(self.state()['attempts'], 1)
            self.assertEqual(self.state()['session_id'], original['session_id'])
            self.assertEqual(self.state()['total_execution_seconds'], original['total_execution_seconds'])
        self.verify()
        self.call('review', '--task', str(self.task), '--review', str(self.review_file()), expect=0)
        self.assertEqual(self.state()['status'], 'ACCEPTED')
        self.assertEqual(self.state()['attempts'], 1)

    def test_changed_final_logs_cannot_refund_reserved_budget(self):
        self.interrupt_execution_commit()
        for name in ('events.ndjson', 'stderr.log'):
            with self.subTest(log=name):
                log = self.task / 'attempts/001' / name
                original = log.read_bytes()
                log.write_bytes(original + b'changed after execution\n')
                state_before = (self.task / 'state.json').read_bytes()
                self.recover(expect=3)
                self.assertIn('Final execution log changed', self.last_err)
                self.assertEqual((self.task / 'state.json').read_bytes(), state_before)
                log.write_bytes(original)  # Test fixture only; never rewrite user evidence.
        self.recover()
        self.assertEqual(self.state()['operation']['budget']['status'], 'settled_observed')

    def test_torn_execution_record_exhausts_unknown_budget_once(self):
        self.interrupt_execution_commit()
        record = self.task / 'attempts/001/execution.json'
        record.write_text('{')
        self.recover()
        state = self.state()
        self.assertEqual(state['total_execution_seconds'], 10)
        self.assertEqual(state['operation']['budget']['status'], 'settled_unknown')
        self.assertIsNone(state['operation']['budget']['observed_seconds'])
        self.assertEqual(record.read_text(), '{')
        before = (self.task / 'state.json').read_bytes()
        self.recover(expect=3)
        self.assertEqual((self.task / 'state.json').read_bytes(), before)

    def test_execution_record_write_failure_does_not_release_time(self):
        self.contract.update(max_execution_seconds=10, timeout_seconds=2)
        self.init()
        original = d.atomic_json
        def fail(path, value):
            if path.name == 'execution.json':
                raise OSError('injected execution record write failure')
            return original(path, value)
        with patch.object(d, 'atomic_json', side_effect=fail):
            self.run_worker(expect=2)
        self.assertFalse((self.task / 'attempts/001/execution.json').exists())
        self.recover()
        self.assertEqual(self.state()['total_execution_seconds'], 10)
        self.assertEqual(self.state()['operation']['budget']['status'], 'settled_unknown')


if __name__ == '__main__':
    unittest.main(verbosity=2)
