#!/usr/bin/env python3
"""C01-C03 acceptance: full lifecycle, crash accounting, and real POSIX children.

No provider/model calls. Signals are sent only to processes created by the test.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import test_delegate as old
import test_lifecycle_fixes as lifecycle_tests
import execution_budget as budget
import process_control as pc

d = old.d


class RecoveryBudgetTests(unittest.TestCase):
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

    def checkpoint(self):
        p = self.root / 'handoff.md'
        p.write_text('All test processes stopped. Reviewed unchanged scope and baseline. No result accepted.')
        return ('--fresh-session', '--checkpoint', str(p))

    def transient_verifier(self):
        self.contract['verification_artifacts'] = ['cache/']
        self.check_command("from pathlib import Path; import time; p=Path('cache/once'); "
                           "first=not p.exists(); p.parent.mkdir(exist_ok=True); p.write_text('attempted'); "
                           "time.sleep(3) if first else None; "
                           "assert Path('allowed.txt').read_text()=='fixed\\n'; print('PASS')", ['PASS'])
        self.contract['checks'][0]['timeout_seconds'] = 1

    def test_c01_last_worker_verify_retry_review_without_model(self):
        self.contract['max_attempts'] = 1
        self.transient_verifier(); self.init(); self.run_worker('edit')
        original = self.state()
        result = (self.task / 'attempts/001/worker-result.json').read_bytes()
        self.verify(expect=5); self.recover()
        restored = self.state()
        self.assertEqual(restored['status'], 'VERIFY_RETRY_READY')
        self.assertEqual(restored['session_id'], original['session_id'])
        self.assertEqual(restored['total_execution_seconds'], original['total_execution_seconds'])
        self.assertIsNone(restored['verification'])
        self.run_worker(extra=self.checkpoint(), expect=3)
        self.assertIn('VERIFY_RETRY_READY', self.last_err)
        self.verify()
        self.call('review', '--task', str(self.task), '--review', str(self.review_file()), expect=0)
        self.assertEqual(self.state()['status'], 'ACCEPTED')
        self.assertEqual(self.state()['attempts'], 1)
        self.assertEqual((self.task / 'attempts/001/worker-result.json').read_bytes(), result)

    def test_c01_worker_recovery_is_not_verification_ready(self):
        self.contract['timeout_seconds'] = 1
        self.init(); self.run_worker('timeout', expect=4); self.recover()
        self.assertEqual(self.state()['status'], 'RECOVERED')
        self.verify(expect=3)
        self.assertIn('Cannot verify', self.last_err)

    def test_c01_source_pollution_still_blocks_verify(self):
        self.contract['max_attempts'] = 1
        self.check_command("from pathlib import Path; import time; Path('allowed.txt').write_text('pollution'); time.sleep(3)")
        self.contract['checks'][0]['timeout_seconds'] = 1
        self.init(); self.run_worker('edit'); self.verify(expect=5); self.recover(expect=3)
        self.assertEqual(self.state()['status'], 'VERIFICATION_MUTATED_SOURCE')
        self.verify(expect=3)

    def test_c01_retry_fails_normally_can_return_to_worker_with_spare_budget(self):
        self.contract['verification_artifacts'] = ['cache/']
        self.check_command("from pathlib import Path; import time; p=Path('cache/once'); f=not p.exists(); p.parent.mkdir(exist_ok=True); p.write_text('seen'); time.sleep(3) if f else None; raise SystemExit(1)")
        self.contract['checks'][0]['timeout_seconds'] = 1
        self.init(); self.run_worker(); self.verify(expect=5); self.recover(); self.verify(expect=5)
        self.assertEqual(self.state()['status'], 'NEEDS_FIX')
        feedback = self.root / 'feedback.md'; feedback.write_text('Frozen check C1 failed. Investigate without changing tests.')
        self.run_worker(extra=('--feedback', str(feedback)))
        self.assertEqual(self.state()['attempts'], 2)

    def test_c02_reservation_precedes_every_launch(self):
        self.contract.update(max_execution_seconds=5, timeout_seconds=3)
        self.init()
        original = d.execute
        def inspect(*args, **kwargs):
            s = self.state()
            self.assertEqual(s['status'], 'RUNNING')
            self.assertEqual(s['total_execution_seconds'], 3)
            self.assertEqual(s['operation']['budget']['status'], 'reserved')
            return original(*args, **kwargs)
        with patch.object(d, 'execute', side_effect=inspect): self.run_worker()
        s = self.state()
        self.assertEqual(s['operation']['budget']['status'], 'settled_observed')
        self.assertLess(s['total_execution_seconds'], 3)

    def test_c02_final_state_failure_settles_bound_execution_once(self):
        self.contract.update(max_execution_seconds=1, timeout_seconds=5)
        self.init(); save = d.save
        def fail(task, state, cp=None):
            if state['operation']['stage'] == 'uncertain': raise OSError('final state fault')
            return save(task, state, cp)
        with patch.object(d, 'save', side_effect=fail): self.run_worker('timeout', expect=2)
        self.assertEqual(self.state()['total_execution_seconds'], 1)
        measured = json.loads((self.task / 'attempts/001/execution.json').read_text())['elapsed_seconds']
        self.recover()
        self.assertAlmostEqual(self.state()['total_execution_seconds'], measured)
        before = (self.task / 'state.json').read_bytes()
        self.recover(expect=3)
        self.assertEqual((self.task / 'state.json').read_bytes(), before)
        self.run_worker(extra=self.checkpoint(), expect=3)
        self.assertIn('budget exhausted', self.last_err)

    def test_c02_recovery_commit_failure_is_idempotent(self):
        self.init(); save = d.save
        def fail_finished(task, state, cp=None):
            if state['operation']['stage'] == 'finished': raise OSError('final commit fault')
            return save(task, state, cp)
        with patch.object(d, 'save', side_effect=fail_finished): self.run_worker(expect=2)
        amount = json.loads((self.task / 'attempts/001/execution.json').read_text())['elapsed_seconds']
        def fail_recovery(task, state, cp=None):
            if state['status'] == 'RECOVERED': raise OSError('recovery commit fault')
            return save(task, state, cp)
        with patch.object(d, 'save', side_effect=fail_recovery): self.recover(expect=2)
        self.recover()
        self.assertAlmostEqual(self.state()['total_execution_seconds'], amount)
        c, s, _, _ = d.load(self.task)
        budget.recover_accounting(self.task, s, c)
        self.assertAlmostEqual(s['total_execution_seconds'], amount)

    def test_c02_missing_execution_record_consumes_unknown_remaining_budget(self):
        self.contract.update(max_execution_seconds=7, timeout_seconds=2)
        self.init(); execute = d.execute
        def lost(*args, **kwargs):
            execute(*args, **kwargs)
            raise OSError('supervisor failed before execution record')
        with patch.object(d, 'execute', side_effect=lost): self.run_worker(expect=2)
        self.assertEqual(self.state()['total_execution_seconds'], 2)
        self.recover()
        self.assertEqual(self.state()['total_execution_seconds'], 7)
        self.assertIsNone(self.state()['operation']['budget']['observed_seconds'])
        self.run_worker(extra=self.checkpoint(), expect=3)

    def test_c02_known_preparing_never_launched_releases_reservation(self):
        self.contract.update(max_execution_seconds=7, timeout_seconds=2)
        self.init(); write = d.atomic_json
        def fail(path, value):
            if path.name == 'packet.json': raise OSError('prepare fault')
            return write(path, value)
        with patch.object(d, 'atomic_json', side_effect=fail): self.run_worker(expect=2)
        self.assertEqual(self.state()['total_execution_seconds'], 2)
        self.recover()
        self.assertEqual(self.state()['total_execution_seconds'], 0)
        self.assertEqual(self.state()['operation']['budget']['status'], 'settled_not_started')
        self.run_worker(extra=self.checkpoint())

    def test_c02_wrong_operation_record_is_not_accepted_as_time_evidence(self):
        self.init(); save = d.save
        def fail(task, state, cp=None):
            if state['operation']['stage'] == 'finished': raise OSError('commit fault')
            return save(task, state, cp)
        with patch.object(d, 'save', side_effect=fail): self.run_worker(expect=2)
        p = self.task / 'attempts/001/execution.json'
        value = json.loads(p.read_text()); value['operation_id'] = 'other'; p.write_text(json.dumps(value))
        previous = (self.task / 'state.json').read_bytes()
        self.recover(expect=3)
        self.assertEqual((self.task / 'state.json').read_bytes(), previous)

    def test_c02_legacy_active_run_is_not_silently_given_free_budget(self):
        self.init(); _, s, _, cp = d.load(self.task)
        s.update(status='RUNNING', attempts=1)
        s['operation'] = {'id':'old-op', 'phase':'run', 'stage':'running', 'start_sha256':cp['sha256'], 'errors':[]}
        d.save(self.task, s)
        self.recover()
        self.assertEqual(self.state()['operation']['budget']['status'], 'settled_unknown_legacy')
        self.assertEqual(self.state()['total_execution_seconds'], 1800)

    def test_c02_negative_nan_or_unbound_elapsed_never_releases_budget(self):
        for value in [-1, float('nan'), float('inf'), True]:
            s = {'total_execution_seconds':0, 'contract_sha256':'c', 'status':'RUNNING',
                 'operation':{'id':'op','phase':'run','stage':'running'}}
            s['operation']['budget'] = budget.reserve(s, 2, 5)
            with self.assertRaises(d.GuardError):
                budget.settle(s, {'operation_id':'op','contract_sha256':'c','elapsed_seconds':value,
                                  'process_group_quiescent':True}, task_limit=5)
            self.assertEqual(s['total_execution_seconds'], 2)

    def test_c02_live_supervisor_kill_never_refunds_unknown_time(self):
        self.contract.update(max_execution_seconds=5, timeout_seconds=2)
        self.init(); os.environ['MOCK_SCENARIO'] = 'timeout'
        argv = [sys.executable, str(Path(d.__file__)), 'run', '--task', str(self.task), '--opencode', str(self.binary),
                '--authorize-implementation', '--acknowledge-local-execution', '--experimental-cli-version', '1.2.0']
        leader = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=dict(os.environ))
        worker = None
        try:
            until = time.monotonic() + 8
            while time.monotonic() < until:
                s = self.state()
                if s.get('process_pid') and s['operation']['stage'] == 'running':
                    worker = s['process_pid']; break
                time.sleep(.02)
            self.assertIsNotNone(worker)
            time.sleep(.15)
            leader.kill(); leader.wait(timeout=2)
            os.killpg(worker, signal.SIGKILL)
            # Reap an adopted worker on Linux; macOS init normally reaps it.
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                try: os.waitpid(worker, os.WNOHANG)
                except ChildProcessError: pass
                if not d.group_alive(worker): break
                time.sleep(.02)
            self.assertFalse(d.group_alive(worker))
            self.recover()
            self.assertEqual(self.state()['total_execution_seconds'], 5)
            self.run_worker(extra=self.checkpoint(), expect=3)
        finally:
            if leader.poll() is None: leader.kill(); leader.wait(timeout=2)
            if worker:
                try: os.killpg(worker, signal.SIGKILL)
                except ProcessLookupError: pass
                try: os.waitpid(worker, os.WNOHANG)
                except ChildProcessError: pass

    def test_c03_normal_exit_has_final_immutable_logs(self):
        out, err = self.root / 'out', self.root / 'err'
        result = d.execute([sys.executable, '-c', "print('done')"], self.root, dict(os.environ), 3, out, err)
        self.assertIsNone(result['reason'])
        self.assertTrue(result['process_group_quiescent'])
        self.assertEqual(result['log_evidence'], 'final')
        self.assertEqual(d.file_hash(out), result['stdout_sha256'])

    def test_c03_normal_leader_exit_escalates_term_resistant_same_group(self):
        out, err = self.root / 'out', self.root / 'err'
        pidfile = self.root / 'child.pid'
        code = """import os, signal, time, sys
pid=os.fork()
if pid:
    limit=time.monotonic()+3
    while not os.path.exists(sys.argv[1]) and time.monotonic()<limit: time.sleep(.01)
    os._exit(0)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
with open(sys.argv[1], 'w') as f: f.write(str(os.getpid()))
while True:
    os.write(1,b'alive\\n'); time.sleep(.03)
"""
        result = None
        try:
            result = d.execute([sys.executable, '-c', code, str(pidfile)], self.root, dict(os.environ), 4, out, err)
            self.assertEqual(result['exit_code'], 0)
            self.assertEqual(result['reason'], 'descendants_still_running')
            self.assertIn('SIGTERM', result['cleanup']['signals'])
            self.assertIn('SIGKILL', result['cleanup']['signals'])
            first = out.read_bytes(); time.sleep(.15)
            self.assertEqual(out.read_bytes(), first)
            child = int(pidfile.read_text())
            try:
                waited, _ = os.waitpid(child, os.WNOHANG)
                self.assertEqual(waited, child, 'adopted child must already have terminated')
            except ChildProcessError:
                pass  # macOS init can reap the orphan independently.
            if result['process_group_quiescent']:
                self.assertEqual(result['stdout_sha256'], d.file_hash(out))
            else:
                self.assertEqual(result['log_evidence'], 'unstable')
                self.assertIsNone(result['stdout_sha256'])
        finally:
            if result:
                try: os.killpg(result['pid'], signal.SIGKILL)
                except ProcessLookupError: pass
            if pidfile.exists():
                try: os.waitpid(int(pidfile.read_text()), os.WNOHANG)
                except ChildProcessError: pass

    def test_c03_uncertain_cleanup_is_not_final_evidence(self):
        out, err = self.root / 'out', self.root / 'err'
        with patch.object(d, 'terminate_group', return_value={'signals':[], 'errors':['simulated'],
                                                              'process_group_quiescent':False, 'leader_reaped':True}):
            result = d.execute([sys.executable, '-c', "print('done')"], self.root, dict(os.environ), 2, out, err)
        self.assertEqual(result['reason'], 'termination_unconfirmed')
        self.assertIsNone(result['stdout_sha256'])
        self.assertEqual(result['log_evidence'], 'unstable')

    def test_c03_timeout_uses_same_escalation(self):
        out, err = self.root / 'out', self.root / 'err'
        code = 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(5)'
        result = d.execute([sys.executable, '-c', code], self.root, dict(os.environ), 1, out, err)
        self.assertEqual(result['reason'], 'timeout')
        self.assertEqual(result['cleanup']['signals'], ['SIGTERM','SIGKILL'])
        self.assertTrue(result['process_group_quiescent'])
        self.assertLess(result['elapsed_seconds'], 8)  # generous CI scheduling tolerance

    def test_snapshot_count_is_not_a_cost_benchmark(self):
        self.check_command("print('PASS')", ['PASS'])
        second = dict(self.contract['checks'][0]); second['id'] = 'C2'
        self.contract['checks'].append(second)
        with patch.object(d, 'snapshot', wraps=d.snapshot) as measured:
            self.init(); self.run_worker('edit'); self.verify()
            self.call('review', '--task', str(self.task), '--review', str(self.review_file()), expect=0)
            self.assertEqual(measured.call_count, 2 + 6)
            self.call('export', '--task', str(self.task), '--output', str(self.root / 'delivery.zip'), expect=0)
            self.call('cleanup', '--task', str(self.task), '--confirm', expect=0)
            self.assertEqual(measured.call_count, 2 + 9)

    def test_c03_unstable_failure_details_are_withheld_until_reverification(self):
        self.check_command("print('PASS')", ['PASS'])
        self.init(); self.run_worker('edit')
        with patch.object(d, 'terminate_group', return_value={'signals':[], 'errors':['simulated'],
                                                              'process_group_quiescent':False, 'leader_reaped':True}):
            self.verify(expect=5)
        self.assertEqual(self.state()['status'], 'OUTCOME_UNKNOWN')
        self.call('failure', '--task', str(self.task), '--include-details', expect=0)
        item = json.loads(self.last_out)['checks'][0]
        self.assertIn('details_withheld', item)
        self.assertNotIn('reviewed_excerpts', item)
        self.recover(); self.verify()
        self.assertEqual(self.state()['attempts'], 1)

    @classmethod
    def setUpClass(cls):
        # Reap only the test-created orphans, avoiding zombies under container PID 1.
        cls.subreaper = None
        if sys.platform.startswith('linux'):
            libc = ctypes.CDLL(None)
            previous = ctypes.c_int()
            if libc.prctl(37, ctypes.byref(previous), 0, 0, 0) == 0 and libc.prctl(36, 1, 0, 0, 0) == 0:
                cls.subreaper = (libc, previous.value)

    @classmethod
    def tearDownClass(cls):
        if cls.subreaper: cls.subreaper[0].prctl(36, cls.subreaper[1], 0, 0, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
