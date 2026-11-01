#!/usr/bin/env python3
"""Round-two regression acceptance tests; synthetic CLI events are NOT certification."""
import copy
import fnmatch
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import test_delegate as old
import opencode_adapter as adapter
import lifecycle
import state_store

d = old.d


class LifecycleTests(unittest.TestCase):
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

    def recover(self, expect=0):
        note = self.root / 'recovery.md'
        note.write_text('Test-only reconciliation: inspected process and changes; no process survives.')
        return self.call('recover', '--task', str(self.task), '--confirmed-stopped', '--note', str(note), expect=expect)

    def accept(self):
        self.init(); self.run_worker('edit'); self.verify()
        self.call('review', '--task', str(self.task), '--review', str(self.review_file()), expect=0)

    def export(self):
        out = self.root / 'delivery.zip'
        self.call('export', '--task', str(self.task), '--output', str(out), expect=0)
        return out

    def external_rule(self):
        rule = self.root / 'external.md'; rule.write_text('Frozen requirement.')
        self.contract['instruction_sources'] = [{'path': str(rule), 'scope': 'whole task'}]
        return rule

    def test_a01_verifier_source_change_survives_timeout_recovery(self):
        self.check_command("from pathlib import Path; import time; Path('allowed.txt').write_text('verifier change'); time.sleep(5)")
        self.contract['checks'][0]['timeout_seconds'] = 1
        self.init(); self.run_worker(); self.verify(expect=5)
        self.assertEqual(self.state()['status'], 'OUTCOME_UNKNOWN')
        self.recover(expect=3)
        self.assertEqual(self.state()['status'], 'VERIFICATION_MUTATED_SOURCE')

    def test_a01_legal_artifacts_survive_timeout_recovery(self):
        self.contract['verification_artifacts'] = ['cache/']
        self.check_command("from pathlib import Path; import time; Path('cache').mkdir(); Path('cache/report').write_text('output'); time.sleep(5)")
        self.contract['checks'][0]['timeout_seconds'] = 1
        self.init(); self.run_worker(); self.verify(expect=5)
        self.recover()
        self.assertEqual(self.state()['status'], 'VERIFY_RETRY_READY')
        self.assertEqual(self.state()['operation']['phase'], 'verify')

    def test_a01_crash_without_report_uses_start_snapshot(self):
        self.check_command("print('pass')"); self.init(); self.run_worker()
        def crash(*args, **kwargs):
            (self.task / 'worktree/allowed.txt').write_text('test wrote source')
            raise OSError('injected test supervisor crash')
        with patch.object(d, 'execute', side_effect=crash):
            self.verify(expect=2)
        self.assertEqual(self.state()['status'], 'VERIFYING')
        self.assertIsNone(self.state()['verification'])
        self.recover(expect=3)
        self.assertEqual(self.state()['status'], 'VERIFICATION_MUTATED_SOURCE')

    def test_a01_recorded_violation_cannot_be_erased_by_reverting_file(self):
        self.check_command("from pathlib import Path; import time; Path('allowed.txt').write_text('changed'); time.sleep(5)")
        self.contract['checks'][0]['timeout_seconds'] = 1
        self.init(); self.run_worker(); self.verify(expect=5)
        (self.task / 'worktree/allowed.txt').write_text('original\n')
        self.recover(expect=3)
        self.assertEqual(self.state()['status'], 'VERIFICATION_MUTATED_SOURCE')

    def test_a01_unknown_legacy_phase_is_not_guessed(self):
        self.init(); _, s, _, _ = d.load(self.task)
        s['status'] = 'OUTCOME_UNKNOWN'; d.save(self.task, s)
        self.recover(expect=3)
        self.assertIn('No durable operation phase', self.last_err)

    def attempt_fault(self, boundary):
        self.init()
        original_write, original_save, original_mkdir = d.atomic_json, d.save, Path.mkdir
        def write(path, value):
            if path.name == boundary:
                raise OSError('injected preparation write failure')
            return original_write(path, value)
        def save(task, state, cp=None):
            if boundary == 'running' and state['status'] == 'RUNNING' and not state.get('process_pid'):
                raise OSError('injected RUNNING commit failure')
            if boundary == 'pid' and state['status'] == 'RUNNING' and state.get('process_pid'):
                raise OSError('injected process identity commit failure')
            return original_save(task, state, cp)
        def mkdir(path, *args, **kwargs):
            if boundary == 'mkdir' and path.name == '001':
                raise OSError('injected mkdir failure')
            return original_mkdir(path, *args, **kwargs)
        with patch.object(d, 'atomic_json', side_effect=write), patch.object(d, 'save', side_effect=save), patch.object(Path, 'mkdir', mkdir):
            self.run_worker('timeout' if boundary == 'pid' else 'ok', expect=2)
        self.assertEqual(self.state()['attempts'], 1)
        self.assertIn(self.state()['status'], ('PREPARING', 'RUNNING'))
        self.recover()
        checkpoint = self.root / 'checkpoint.md'; checkpoint.write_text('Prepared attempt reconciled. No result accepted; scope unchanged.')
        if boundary == 'pid':
            # The process was started but its identity/evidence commit failed.
            # Unknown runtime must not be treated as free execution time.
            self.run_worker(extra=('--fresh-session', '--checkpoint', str(checkpoint)), expect=3)
            self.assertIn('budget exhausted', self.last_err)
            self.assertEqual(self.state()['attempts'], 1)
            self.assertFalse((self.task / 'attempts/002').exists())
        else:
            self.run_worker(extra=('--fresh-session', '--checkpoint', str(checkpoint)))
            self.assertEqual(self.state()['attempts'], 2)
            self.assertTrue((self.task / 'attempts/002/worker-result.json').is_file())

    def test_a02_packet_write_failure_recovers(self): self.attempt_fault('packet.json')
    def test_a02_policy_write_failure_recovers(self): self.attempt_fault('requested-policy.json')
    def test_a02_operation_marker_failure_recovers(self): self.attempt_fault('operation.json')
    def test_a02_mkdir_failure_recovers(self): self.attempt_fault('mkdir')
    def test_a02_running_commit_failure_recovers(self): self.attempt_fault('running')
    def test_a02_pid_commit_failure_recovers_without_duplicate_launch(self): self.attempt_fault('pid')

    def test_a02_intent_failure_has_no_attempt_side_effect(self):
        self.init()
        with patch.object(lifecycle, 'save', side_effect=OSError('intent commit failed')):
            self.run_worker(expect=2)
        self.assertEqual(self.state()['status'], 'READY')
        self.assertFalse((self.task / 'attempts/001').exists())
        self.run_worker()

    def test_a02_unregistered_prepare_changes_are_rejected(self):
        self.init()
        _, s, _, cp = d.load(self.task)
        lifecycle.begin(self.task, s, cp, 'run', 'PREPARING')
        (self.task / 'worktree/allowed.txt').write_text('external edit')
        self.recover(expect=3)
        self.assertEqual(self.state()['status'], 'POLICY_VIOLATION')

    def test_a03_override_is_frozen_and_postexecution_protected(self):
        folder = self.repo / 'src'; folder.mkdir()
        (folder / 'AGENTS.override.md').write_text('Keep tests.')
        self.git('add', '.'); self.git('commit', '-qm', 'rule')
        self.contract['allowed_paths'] = ['src/']
        self.assertEqual(self.init(), 0)
        entries = json.loads((self.task / 'instructions.json').read_text())
        self.assertIn('src/AGENTS.override.md', [x['worktree_path'] for x in entries])
        c, s, base, cp = d.load(self.task)
        (self.task / 'worktree/src/AGENTS.override.md').write_text('changed')
        self.assertIn('Protected path changed: src/AGENTS.override.md', d.invariant_errors(c, base, cp, d.snapshot(self.task / 'worktree'), 'run'))

    def test_a03_new_case_variants_denied_by_both_candidate_policies(self):
        self.contract['allowed_paths'] = ['src/']; self.init()
        c, _, _, _ = d.load(self.task); wt = self.task / 'worktree'
        for major in (1, 2):
            config, ak, pk = adapter.permission_config(c, major, wt)
            policy = config[ak][d.AGENT][pk]
            patterns = list(policy['edit'].items()) if major == 1 else [(x['resource'], x['effect']) for x in policy if x['action'] in ('*', 'edit')]
            for stem in ('agents', 'claude'):
                for chars in itertools.product(*[(ch, ch.upper()) for ch in stem]):
                    for suffix in ('.md', '.override.md', '.OVERRIDE.MD'):
                        rel = 'src/' + ''.join(chars) + suffix
                        for path in (rel, str(wt / rel)):
                            decision = [effect for pat, effect in patterns if fnmatch.fnmatchcase(path, pat)][-1]
                            self.assertEqual(decision, 'deny', (major, path))
            self.assertLess(len(json.dumps(config).encode()), 100000, 'Policy must fit normal exec environment limits')

    def test_a03_custom_rules_remain_protected(self):
        (self.repo / 'team-policy.txt').write_text('Custom fallback.')
        self.git('add', '.'); self.git('commit', '-qm', 'custom rule')
        self.contract['context'].append({'path': 'team-policy.txt', 'kind': 'rule', 'purpose': 'declared fallback'})
        self.init(); c, _, _, _ = d.load(self.task)
        self.assertIn('team-policy.txt', c['protected_paths'])

    def test_a03_codex_global_override_must_be_declared(self):
        rule = Path(os.environ['CODEX_HOME']) / 'AGENTS.override.md'
        rule.parent.mkdir(parents=True); rule.write_text('Coordinator global rule')
        self.assertEqual(self.init(), 3)
        self.assertIn('Declare/review ambient rules', self.last_err)

    def test_a04_final_review_rechecks_external_rules(self):
        rule = self.external_rule(); self.init(); self.run_worker(); self.verify()
        rule.write_text('Changed rule after verification')
        self.call('review', '--task', str(self.task), '--review', str(self.review_file()), expect=3)
        self.assertEqual(self.state()['status'], 'REVIEW_REQUIRED')

    def test_a04_memory_and_export_recheck_external_rules(self):
        rule = self.external_rule(); self.accept()
        review = json.loads((self.task / self.state()['review']['path']).read_text())
        self.assertEqual(review['instruction_manifest_sha256'], self.state()['instruction_manifest_sha256'])
        rule.write_text('Changed after acceptance')
        self.call('export', '--task', str(self.task), '--output', str(self.root / 'out.zip'), expect=3)
        self.call('memory', '--task', str(self.task), '--knowledge', str(self.root / 'not-read.json'), expect=3)
        self.assertIn('Instruction content changed', self.last_err)

    def test_a05_v2_rule_key_order_is_semantically_irrelevant(self):
        self.init(); c, _, _, _ = d.load(self.task); wt = self.task / 'worktree'
        cfg, ak, pk = adapter.permission_config(c, 2, wt)
        changed = copy.deepcopy(cfg)
        for holder in (changed, changed[ak][d.AGENT]):
            holder[pk] = [{k: item[k] for k in sorted(item)} for item in holder[pk]]
        fingerprints = []
        for value in (cfg, changed):
            from test_v2_config import v2_replies
            with patch.object(adapter.subprocess, 'run', side_effect=v2_replies(value)):
                fingerprints.append(adapter.check_effective_config({'binary': str(self.binary)}, cfg, ak, pk, wt, {}))
        self.assertEqual(*fingerprints)

    def test_a05_v2_rule_array_order_remains_semantic(self):
        self.init(); c, _, _, _ = d.load(self.task); wt = self.task / 'worktree'
        cfg, ak, pk = adapter.permission_config(c, 2, wt)
        changed = copy.deepcopy(cfg); changed[ak][d.AGENT][pk].reverse()
        from test_v2_config import v2_replies
        with patch.object(adapter.subprocess, 'run', side_effect=v2_replies(changed)), self.assertRaises(d.GuardError):
            adapter.check_effective_config({'binary': str(self.binary)}, cfg, ak, pk, wt, {})

    def events(self, seq):
        path = self.root / 'events.ndjson'
        path.write_text('\n'.join(json.dumps(x) for x in seq))
        return d.parse_events(path, 't1', None)

    def event(self, typ, mid='m1', text=None, reason=None):
        part = {}
        if mid is not None: part['messageID'] = mid
        if text is not None: part['text'] = text
        if reason is not None: part['reason'] = reason
        return {'type': typ, 'sessionID': 'ses_test', 'part': part}

    def result_text(self, summary='candidate'):
        return 'BEGIN_DELEGATE_RESULT' + json.dumps({'schema_version':1, 'task_id':'t1', 'status':'complete', 'summary':summary, 'claims':[], 'tests_run':[], 'risks':[]}) + 'END_DELEGATE_RESULT'

    def test_a06_old_stop_cannot_complete_new_length_response(self):
        seq = [self.event('text', text=self.result_text()), self.event('step_finish', reason='stop'),
               self.event('text', 'm2', 'unfinished'), self.event('step_finish', 'm2', reason='length')]
        with self.assertRaises(d.GuardError): self.events(seq)

    def test_a06_final_result_must_belong_to_final_message(self):
        seq = [self.event('text', text=self.result_text('old')), self.event('step_finish', reason='stop'),
               self.event('text', 'm2', self.result_text('final')), self.event('step_finish', 'm2', reason='stop')]
        value = self.events(seq)
        self.assertEqual(value['result']['summary'], 'final')
        self.assertEqual(value['final_message_id'], 'm2')

    def test_a06_legacy_new_activity_discards_old_candidate(self):
        seq = [self.event('text', None, self.result_text()), self.event('step_finish', None, reason='stop'),
               self.event('text', None, 'not a result'), self.event('step_finish', None, reason='stop')]
        with self.assertRaises(d.GuardError): self.events(seq)

    def test_a06_mixed_or_conflicting_identities_rejected(self):
        for tail in (self.event('step_finish', None, reason='stop'), self.event('step_finish', 'm2', reason='stop')):
            with self.assertRaises(d.GuardError): self.events([self.event('text', text=self.result_text()), tail])
        bad = self.event('text', text=self.result_text()); bad['messageID'] = 'other'
        with self.assertRaises(d.GuardError): self.events([bad])

    def test_a06_replayed_message_rejected(self):
        seq = [self.event('text', text='first'), self.event('step_finish', reason='stop'),
               self.event('text', 'm2', 'second'), self.event('text', 'm1', self.result_text()), self.event('step_finish', reason='stop')]
        with self.assertRaises(d.GuardError): self.events(seq)

    def test_a06_unknown_event_and_duplicate_stop_rejected(self):
        base = [self.event('text', text=self.result_text()), self.event('step_finish', reason='stop')]
        for tail in (self.event('unknown'), self.event('step_finish', reason='stop'), self.event('tool_use')):
            with self.assertRaises(d.GuardError): self.events(base + [tail])

    def test_a07_cleanup_final_commit_failure_can_be_finished(self):
        self.accept(); out = self.export(); original = d.save
        def fail(task, state, cp=None):
            if state['status'] == 'ARCHIVED': raise OSError('injected final cleanup commit failure')
            return original(task, state, cp)
        with patch.object(d, 'save', side_effect=fail):
            self.call('cleanup', '--task', str(self.task), '--confirm', expect=2)
        self.assertEqual(self.state()['status'], 'CLEANING')
        self.assertFalse((self.task / 'worktree').exists())
        self.assertTrue(out.is_file())
        self.call('cleanup', '--task', str(self.task), '--confirm', expect=0)
        self.assertEqual(self.state()['status'], 'ARCHIVED')
        self.call('cleanup', '--task', str(self.task), '--confirm', expect=0)
        self.assertTrue(json.loads(self.last_out)['already_cleaned'])

    def test_a07_cleanup_intent_failure_does_not_remove_worktree(self):
        self.accept(); self.export()
        with patch.object(lifecycle, 'save', side_effect=OSError('intent failure')):
            self.call('cleanup', '--task', str(self.task), '--confirm', expect=2)
        self.assertTrue((self.task / 'worktree').exists())
        self.assertEqual(self.state()['status'], 'ACCEPTED')
        self.call('cleanup', '--task', str(self.task), '--confirm', expect=0)

    def test_a07_cleanup_git_failure_is_retryable_without_scope_expansion(self):
        self.accept(); self.export(); original = d.git
        def fail(repo, *args, **kwargs):
            if args[:2] == ('worktree', 'remove'): raise d.GuardError('injected remove failure')
            return original(repo, *args, **kwargs)
        with patch.object(d, 'git', side_effect=fail):
            self.call('cleanup', '--task', str(self.task), '--confirm', expect=2)
        self.assertEqual(self.state()['status'], 'CLEANING')
        self.call('cleanup', '--task', str(self.task), '--confirm', expect=0)
        self.assertTrue((self.repo / 'allowed.txt').exists())

    def test_a07_changed_export_after_cleanup_intent_still_blocks(self):
        self.accept(); out = self.export(); original = d.git
        def fail(repo, *args, **kwargs):
            if args[:2] == ('worktree', 'remove'): raise d.GuardError('injected remove failure')
            return original(repo, *args, **kwargs)
        with patch.object(d, 'git', side_effect=fail):
            self.call('cleanup', '--task', str(self.task), '--confirm', expect=2)
        out.write_bytes(b'broken')
        self.call('cleanup', '--task', str(self.task), '--confirm', expect=3)
        self.assertTrue((self.task / 'worktree').exists())

    def test_a07_reappeared_archived_path_is_never_deleted(self):
        self.accept(); self.export(); self.call('cleanup', '--task', str(self.task), '--confirm', expect=0)
        wt = self.task / 'worktree'; wt.mkdir(); (wt / 'new-user-file').write_text('preserve')
        self.call('cleanup', '--task', str(self.task), '--confirm', expect=3)
        self.assertTrue((wt / 'new-user-file').exists())

    def test_a09_status_reads_atomic_state_while_writer_lock_is_held(self):
        self.init()
        with d.locked(self.task):
            self.call('status', '--task', str(self.task), '--check-worktree', expect=0)
            self.assertIn('writer active', json.loads(self.last_out)['scan_skipped'])
            self.run_worker(expect=3)
        self.assertEqual(self.state()['status'], 'READY')

    def test_a09_real_running_process_is_observable(self):
        self.contract['timeout_seconds'] = 2; self.init()
        args = [sys.executable, str(old.HERE / 'delegate.py'), 'run', '--task', str(self.task), '--opencode', str(self.binary), '--authorize-implementation', '--acknowledge-local-execution', '--experimental-cli-version', '1.2.0']
        proc = subprocess.Popen(args, env=dict(os.environ, MOCK_SCENARIO='timeout'), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for _ in range(150):
                if self.state()['status'] == 'RUNNING' and self.state().get('process_pid'): break
                time.sleep(.02)
            self.call('status', '--task', str(self.task), '--check-worktree', expect=0)
            value = json.loads(self.last_out)
            self.assertEqual(value['status'], 'RUNNING')
            self.assertIsNone(value['worktree_matches_checkpoint'])
            self.assertIn('generation', value)
            proc.communicate(timeout=10)
        finally:
            if proc.poll() is None: proc.kill(); proc.communicate()

    def test_a10_fixture_clears_host_home_xdg_and_recursion_flags(self):
        home = self.root / 'host-home'; rule = home / '.config/opencode/AGENTS.md'
        rule.parent.mkdir(parents=True); rule.write_text('Fake host rule')
        env = dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=str(home / '.config'), OPENCODE_DELEGATE_ACTIVE='1', GIT_DIR='/invalid/host/git')
        p = subprocess.run([sys.executable, '-m', 'unittest', 'test_delegate.RunnerTests.test_init_detached_worktree_leaves_source_clean'], cwd=str(old.HERE), env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_a10_explicit_global_rule_is_still_enforced(self):
        rule = Path(os.environ['XDG_CONFIG_HOME']) / 'opencode/AGENTS.md'
        rule.parent.mkdir(parents=True); rule.write_text('Global project rule')
        self.contract['instruction_sources'] = [{'path': str(rule), 'scope': 'global'}]
        self.assertEqual(self.init(), 0)
        rule.write_text('changed')
        self.run_worker(expect=3)
        self.assertIn('Instruction content changed', self.last_err)


if __name__ == '__main__':
    unittest.main(verbosity=2)
