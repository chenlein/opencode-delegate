#!/usr/bin/env python3
"""Review-driven negative tests. Mocks are intentionally NOT CLI certification."""
import copy
import json
import os
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import zipfile

import test_delegate as old
import state_store

d = old.d


class ReviewFixTests(unittest.TestCase):
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

    def feedback(self):
        f = self.root / 'feedback.md'
        f.write_text('Address only the recorded acceptance gap, preserve the contract.')
        return ('--feedback', str(f))

    def test_f01_unknown_claim_never_publishes_success(self):
        self.init()
        original = d.parse_events
        def corrupt(*args):
            value = original(*args)
            value['result']['claims'][0]['criterion_id'] = 'UNKNOWN'
            return value
        with patch.object(d, 'parse_events', side_effect=corrupt):
            self.run_worker(expect=4)
        self.assertEqual(self.state()['status'], 'PROTOCOL_ERROR')
        self.assertFalse((self.task / 'attempts/001/worker-result.json').exists())

    def test_f01_result_write_failure_is_protocol_error(self):
        self.init()
        original = d.atomic_json
        def fail(path, value):
            if path.name == 'worker-result.json':
                raise OSError('injected full disk')
            return original(path, value)
        with patch.object(d, 'atomic_json', side_effect=fail):
            self.run_worker(expect=4)
        self.assertEqual(self.state()['status'], 'PROTOCOL_ERROR')

    def test_f01_success_clears_previous_protocol_error(self):
        self.init(); self.run_worker('bad_json', expect=4)
        checkpoint = self.root / 'checkpoint.md'
        checkpoint.write_text('No accepted result. Scope unchanged; previous mock process stopped.')
        self.run_worker(extra=('--fresh-session', '--checkpoint', str(checkpoint)))
        self.assertNotIn('protocol_error', self.state())

    def test_f02_interrupted_state_commit_retains_complete_old_generation(self):
        self.init()
        _, s, _, cp = d.load(self.task)
        (self.task / 'worktree/allowed.txt').write_text('pending checkpoint\n')
        pending = d.snapshot(self.task / 'worktree')
        original = state_store.atomic_json
        def fail(path, value):
            if path.name == 'state.json':
                raise OSError('injected failure before state commit')
            return original(path, value)
        with patch.object(state_store, 'atomic_json', side_effect=fail):
            with self.assertRaises(OSError):
                d.save(self.task, s, pending)
        self.assertEqual(d.load(self.task)[3]['sha256'], cp['sha256'])
        self.assertTrue((self.task / 'checkpoints' / (pending['sha256'] + '.json')).is_file())
        self.call('status', '--task', str(self.task), '--check-worktree', expect=0)
        self.assertFalse(json.loads(self.last_out)['worktree_matches_checkpoint'])

    def test_f02_checkpoint_write_failure_preserves_state(self):
        self.init()
        _, s, _, cp = d.load(self.task)
        (self.task / 'worktree/allowed.txt').write_text('new\n')
        pending = d.snapshot(self.task / 'worktree')
        original = state_store.atomic_json
        def fail(path, value):
            if path.parent.name == 'checkpoints':
                raise OSError('injected checkpoint write failure')
            return original(path, value)
        with patch.object(state_store, 'atomic_json', side_effect=fail):
            with self.assertRaises(OSError):
                d.save(self.task, s, pending)
        self.assertEqual(d.load(self.task)[3], cp)

    def test_f02_immutable_checkpoint_tampering_rejected(self):
        self.init()
        path = self.task / 'checkpoints' / (self.state()['checkpoint_sha256'] + '.json')
        value = json.loads(path.read_text()); value['head'] = 'tampered'
        path.write_text(json.dumps(value))
        self.call('status', '--task', str(self.task), expect=2)

    def test_f03_overlap_is_symmetric_and_boundary_aware(self):
        for a, b in [('generated/', 'generated/'), ('src/', 'src/a/'), ('src/a.py', 'src/'), ('src', 'src/')]:
            self.assertTrue(d.paths_overlap(a, b), (a, b))
            self.assertTrue(d.paths_overlap(b, a), (a, b))
        for a, b in [('src/', 'src-other/'), ('src/a.py', 'src/b.py')]:
            self.assertFalse(d.paths_overlap(a, b))

    def test_f03_equal_artifact_source_rejected_at_init(self):
        self.contract.update(allowed_paths=['generated/'], verification_artifacts=['generated/'])
        self.assertNotEqual(self.init(), 0)

    def test_f03_late_rule_participates_in_artifact_intersection(self):
        self.contract['verification_artifacts'] = ['rules/']
        self.contract['context'] = [{'path':'rules/policy.md', 'kind':'rule', 'purpose':'frozen rule'}]
        self.assertNotEqual(self.init(), 0)

    def test_f04_git_diff_error_blocks_review_and_can_be_reverified(self):
        self.init(); self.run_worker('edit')
        original = d.git
        def fail(repo, *args, **kwargs):
            if args[:2] == ('diff', '--binary'):
                return subprocess.CompletedProcess(args, 128, b'', b'injected diff failure')
            return original(repo, *args, **kwargs)
        with patch.object(d, 'git', side_effect=fail):
            self.verify(expect=5)
        self.assertEqual(self.state()['status'], 'EVIDENCE_ERROR')
        v = d.verify_evidence(self.task, self.state())
        self.assertFalse(v['all_checks_passed'])
        self.assertFalse(d.evidence_valid('diff', v, self.task / 'worktree'))
        self.verify()

    def test_f04_successful_empty_diff_is_distinct(self):
        self.init(); self.run_worker(); self.verify()
        report = d.verify_evidence(self.task, self.state())
        self.assertTrue(report['diff_result']['complete'])
        self.assertEqual(report['diff_result']['exit_code'], 0)

    def test_f04_patch_write_failure_blocks_review(self):
        self.init(); self.run_worker('edit')
        original = Path.write_bytes
        def fail(path, data):
            if path.name == 'tracked.patch':
                raise OSError('injected patch write failure')
            return original(path, data)
        with patch.object(Path, 'write_bytes', fail):
            self.verify(expect=5)
        self.assertEqual(self.state()['status'], 'EVIDENCE_ERROR')
        self.assertFalse(d.verify_evidence(self.task, self.state())['all_checks_passed'])

    def test_f05_uncertified_cli_needs_exact_explicit_opt_in(self):
        self.init()
        self.call('run', '--task', str(self.task), '--opencode', str(self.binary), '--authorize-implementation', '--acknowledge-local-execution', expect=3)
        self.assertFalse((self.root / 'calls.json').exists())
        self.assertEqual(d.probe(str(self.binary))['certification'], 'unverified')

    def test_f06_failure_evidence_can_support_needs_fix(self):
        self.check_command('raise SystemExit(9)')
        self.init(); self.run_worker(); self.verify(expect=5)
        path = self.review_file('needs_fix')
        r = json.loads(path.read_text()); r['criteria'][0].update(result='fail', evidence=['test:C1'])
        path.write_text(json.dumps(r))
        self.call('review', '--task', str(self.task), '--review', str(path), expect=0)

    def test_f06_failed_or_unrelated_test_cannot_support_pass(self):
        v = {'checks':[{'id':'C1', 'passed':False, 'criterion_ids':['A1']}]}
        self.assertTrue(d.evidence_valid('test:C1', v, self.repo, 'A1', False))
        self.assertFalse(d.evidence_valid('test:C1', v, self.repo, 'A1', True))
        self.assertFalse(d.evidence_valid('test:C1', v, self.repo, 'A2', False))

    def test_f07_external_tests_require_sources(self):
        self.contract['checks'] = [{'id':'C1', 'argv':['{python}','guard.py'], 'criterion_ids':['A1']}]
        self.assertNotEqual(self.init(), 0)

    def test_f07_trusted_source_cannot_be_allowed_for_edit(self):
        (self.repo / 'guard.py').write_text('raise SystemExit(9)\n')
        self.git('add', 'guard.py'); self.git('commit', '-qm', 'trusted guard')
        self.contract['checks'] = [{'id':'C1', 'argv':['{python}','guard.py'], 'criterion_ids':['A1']}]
        self.contract['verification_sources'] = ['guard.py']
        self.contract['allowed_paths'].append('guard.py')
        self.assertNotEqual(self.init(), 0)

    def test_f07_inline_marker_cannot_authorize_external_script(self):
        self.contract['checks'] = [{'id':'C1', 'argv':['{python}','guard.py'], 'criterion_ids':['A1'], 'trusted_inline':True}]
        self.assertNotEqual(self.init(), 0)

    def test_f08_secret_names_block_initialization(self):
        for rel in ['id_rsa', 'nested/id_ed25519', '.ssh/id_ed25519', 'credentials', 'auth.json']:
            p = self.repo / rel; p.parent.mkdir(exist_ok=True); p.write_text('FAKE CREDENTIAL FOR TEST ONLY\n')
        self.git('add', '.'); self.git('commit', '-qm', 'fake sensitive filenames')
        self.assertEqual(self.init(), 3)
        self.assertFalse((self.root / 'calls.json').exists())

    def test_f08_read_rules_and_search_are_conservative(self):
        import fnmatch
        c = d.validate_contract(copy.deepcopy(self.contract))
        config, _, _ = d.permission_config(c, 1, self.repo)
        policy = config['agent'][d.AGENT]['permission']
        for path in ['id_rsa','a/id_rsa','.ssh/id_ed25519','credentials','auth.json','a/auth.json']:
            decision = None
            for pattern, effect in policy['read'].items():
                if fnmatch.fnmatchcase(path, pattern): decision = effect
            self.assertEqual(decision, 'deny', path)
        self.assertEqual(policy['grep'], 'deny')

    def test_f09_config_whitespace_does_not_break_resume(self):
        source = self.binary.read_text().replace('print(json.dumps(config));sys.exit(0)', "print(json.dumps(config, indent=2 if os.environ.get('MOCK_PRETTY') else None));sys.exit(0)")
        self.binary.write_text(source)
        self.init(); self.run_worker()
        with patch.dict(os.environ, {'MOCK_PRETTY':'1'}):
            self.run_worker(extra=self.feedback())

    def test_f09_permission_order_still_changes_fingerprint(self):
        a = {'permission':{'edit':{'*':'deny', 'src/*':'allow'}}, 'model':'x'}
        b = {'model':'x', 'permission':{'edit':{'src/*':'allow', '*':'deny'}}}
        self.assertNotEqual(d.digest(d.normalize_config(a)), d.digest(d.normalize_config(b)))
        c = {'model':'x', 'permission':a['permission']}
        self.assertEqual(d.digest(d.normalize_config(a)), d.digest(d.normalize_config(c)))

    def test_f10_external_rule_content_drift_stops_run(self):
        policy = self.root / 'external-policy.md'; policy.write_text('Original reviewed rule.')
        self.contract['instruction_sources'] = [{'path':str(policy), 'scope':'whole task'}]
        self.init(); policy.write_text('Changed unreviewed rule.')
        self.run_worker(expect=3)
        self.assertFalse((self.root / 'calls.json').exists())

    def test_f10_implicit_repository_rules_are_frozen(self):
        self.contract['context'] = []
        self.init()
        manifest = json.loads((self.task / 'instructions.json').read_text())
        self.assertIn('AGENTS.md', [x['worktree_path'] for x in manifest])

    def test_f11_validation_plan_and_failure_metadata_are_in_delta(self):
        self.check_command("print('API_KEY=sk-abcdefghijklmnopqrstuv'); raise SystemExit(9)")
        self.init(); self.run_worker(); self.verify(expect=5)
        packet = d.failure_packet(self.task, self.state(), False)
        self.assertNotIn('reviewed_excerpts', packet['checks'][0])
        redacted = d.failure_packet(self.task, self.state(), True)
        self.assertNotIn('sk-abcdefghijklmnopqrstuv', json.dumps(redacted))
        self.run_worker(extra=self.feedback())
        task_packet = json.loads((self.task / 'attempts/002/packet.json').read_text())
        self.assertEqual(task_packet['validation_plan'][0]['id'], 'C1')
        self.assertEqual(task_packet['failure_packet']['checks'][0]['exit_code'], 9)

    def test_f11_failure_preview_does_not_share_without_details_flag(self):
        self.check_command("print('API_KEY=sk-abcdefghijklmnopqrstuv'); raise SystemExit(9)")
        self.init(); self.run_worker(); self.verify(expect=5)
        self.call('failure', '--task', str(self.task), expect=0)
        self.assertNotIn('reviewed_excerpts', self.last_out)
        self.call('failure', '--task', str(self.task), '--include-details', expect=0)
        self.assertIn('REDACTED', self.last_out)
        self.assertNotIn('sk-abcdefghijklmnopqrstuv', self.last_out)

    def test_f12_missing_terminal_event_rejected(self):
        source = self.binary.read_text().replace("print(json.dumps({'type':'step_finish',**({} if scenario=='no_session' else {'sessionID':sid}),'part':{'reason':'stop'}}))", '')
        self.binary.write_text(source)
        self.init(); self.run_worker(expect=4)
        self.assertEqual(self.state()['status'], 'PROTOCOL_ERROR')

    def test_f12_duplicate_result_blocks_rejected(self):
        self.binary.write_text(self.binary.read_text().replace('print(json.dumps(event))', 'print(json.dumps(event)); print(json.dumps(event))'))
        self.init(); self.run_worker(expect=4)

    def test_f12_chunked_result_parses_without_injected_newlines(self):
        result = {'schema_version':1,'task_id':'t1','status':'complete','summary':'chunked text','claims':[],'tests_run':[],'risks':[]}
        text = 'BEGIN_DELEGATE_RESULT' + json.dumps(result) + 'END_DELEGATE_RESULT'
        cut = text.index('chunked') + 3
        events = [{'type':'text','sessionID':'ses_chunks','part':{'text':part}} for part in (text[:cut], text[cut:])]
        events.append({'type':'step_finish','sessionID':'ses_chunks','part':{'reason':'stop'}})
        path = self.root / 'events.ndjson'; path.write_text('\n'.join(json.dumps(e) for e in events))
        self.assertEqual(d.parse_events(path, 't1', None)['result']['summary'], 'chunked text')

    def test_f12_duplicate_claims_rejected(self):
        self.binary.write_text(self.binary.read_text().replace("text='BEGIN_DELEGATE_RESULT", "result['claims']*=2\ntext='BEGIN_DELEGATE_RESULT"))
        self.init(); self.run_worker(expect=4)

    def test_f13_status_does_not_rescan_by_default(self):
        self.init()
        with patch.object(d, 'snapshot', side_effect=AssertionError('unexpected scan')):
            self.call('status', '--task', str(self.task), expect=0)
        self.assertIsNone(json.loads(self.last_out)['worktree_matches_checkpoint'])
        self.call('status', '--task', str(self.task), '--check-worktree', expect=0)
        self.assertTrue(json.loads(self.last_out)['worktree_matches_checkpoint'])

    def test_f13_scan_observations_recorded(self):
        self.init(); self.run_worker()
        metrics = self.state()['scan_totals']
        self.assertGreater(metrics['calls'], 1)
        self.assertGreater(metrics['bytes'], 0)
        self.assertGreaterEqual(metrics['seconds'], 0)

    def test_f15_total_execution_budget_blocks_another_attempt(self):
        self.init()
        _, s, _, _ = d.load(self.task)
        s['total_execution_seconds'] = 1800
        d.save(self.task, s)
        self.run_worker(expect=3)

    def test_f15_unknown_usage_is_not_zero(self):
        self.init(); self.run_worker()
        result = json.loads((self.task / 'attempts/001/worker-result.json').read_text())
        self.assertEqual(result['usage_completeness'], 'unknown')
        self.assertIsNone(result['usage_observations'])

    def test_f16_export_covers_added_modified_deleted_and_cleanup_is_explicit(self):
        self.binary.write_text(self.binary.read_text().replace("if scenario=='new_file':", "if scenario=='delivery':\n pathlib.Path('allowed.txt').write_text('fixed\\n');pathlib.Path('other.txt').unlink();pathlib.Path('new.txt').write_text('new\\n')\nif scenario=='new_file':"))
        self.contract['allowed_paths'] = ['allowed.txt', 'other.txt', 'new.txt']
        self.init(); self.run_worker('delivery'); self.verify()
        self.call('review', '--task', str(self.task), '--review', str(self.review_file()), expect=0)
        output = self.root / 'delivery.zip'
        self.call('export', '--task', str(self.task), '--output', str(output), expect=0)
        with zipfile.ZipFile(output) as z:
            manifest = json.loads(z.read('manifest.json'))
            self.assertEqual(set(manifest['files']), {'allowed.txt','other.txt','new.txt'})
            self.assertIsNone(manifest['files']['other.txt']['after'])
            self.assertEqual(z.read('files/new.txt'), b'new\n')
        self.call('cleanup', '--task', str(self.task), expect=0)
        self.assertTrue((self.task / 'worktree').is_dir())
        self.call('cleanup', '--task', str(self.task), '--confirm', expect=0)
        self.assertFalse((self.task / 'worktree').exists())
        self.assertTrue((self.task / 'state.json').is_file())
        self.assertEqual((self.repo / 'other.txt').read_text(), 'original\n')
        self.call('status', '--task', str(self.task), expect=0)
        self.assertEqual(json.loads(self.last_out)['status'], 'ARCHIVED')

    def test_f16_running_task_cannot_export_or_cleanup(self):
        self.init()
        self.call('export', '--task', str(self.task), '--output', str(self.root / 'out.zip'), expect=3)
        self.call('cleanup', '--task', str(self.task), '--confirm', expect=3)

    def test_f16_tampered_review_blocks_export(self):
        self.init(); self.run_worker('edit'); self.verify()
        self.call('review', '--task', str(self.task), '--review', str(self.review_file()), expect=0)
        (self.task / self.state()['review']['path']).write_text('{}')
        self.call('export', '--task', str(self.task), '--output', str(self.root / 'out.zip'), expect=3)
        self.assertFalse((self.root / 'out.zip').exists())

    def test_f17_product_patch_version_is_not_state_schema(self):
        self.init()
        state = self.state(); state['runner_version'] = '2.0.1-rc.0'
        (self.task / 'state.json').write_text(json.dumps(state))
        self.call('status', '--task', str(self.task), expect=0)
        self.run_worker()

    def test_f17_legacy_state_read_only_and_preserved(self):
        self.init()
        _, s, _, cp = d.load(self.task)
        (self.task / 'checkpoint.json').write_text(json.dumps(cp))
        s.pop('state_schema_version'); s['runner_version'] = '2.0.0'
        (self.task / 'state.json').write_text(json.dumps(s))
        before = (self.task / 'state.json').read_bytes()
        self.call('status', '--task', str(self.task), expect=0)
        self.assertTrue(json.loads(self.last_out)['legacy_read_only'])
        self.run_worker(expect=3)
        self.assertEqual((self.task / 'state.json').read_bytes(), before)

    def test_f17_unknown_schema_never_rewritten(self):
        self.init()
        s = self.state(); s['state_schema_version'] = 999
        (self.task / 'state.json').write_text(json.dumps(s))
        self.call('status', '--task', str(self.task), expect=2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
