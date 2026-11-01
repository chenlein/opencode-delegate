"""V2 explicit-session location overrides caller cwd; offline regression only."""
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import opencode_adapter as adapter
from delegate_core import AGENT, GuardError
import test_delegate as fixture


class NativeBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.wt = Path(self.tmp.name).resolve()
        self.info = {'major': 2, 'binary': '/fixture/opencode'}
        self.contract = {'model': 'openai/test-model'}
        self.value = {'data': {'id': 'ses_owned', 'agent': AGENT,
                              'model': {'providerID': 'openai', 'id': 'test-model', 'variant': 'default'},
                              'location': {'directory': str(self.wt)}}}

    def check(self, value=None):
        data = self.value if value is None else value
        with patch.object(adapter.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(data).encode(), b'')) as run:
            result = adapter.check_session_binding(self.info, self.contract, 'ses_owned', self.wt, {'PWD': str(self.wt)})
            self.assertEqual(run.call_args.args[0][1:], ['api', 'GET', '/api/session/ses_owned', '--standalone'])
            self.assertEqual(run.call_args.kwargs['cwd'], str(self.wt))
            self.assertEqual(run.call_args.kwargs['timeout'], 5)
            return result

    def test_exact_session_binding_is_returned_without_raw_metadata(self):
        self.value['data']['metadata'] = {'unrelated': 'not persisted'}
        result = self.check()
        self.assertEqual(result['session_id'], 'ses_owned')
        self.assertNotIn('metadata', result)

    def test_session_permissions_absent_empty_and_deny_only_are_safe(self):
        self.check()  # Upstream optional field: absent means no session rules.
        for rules in ([], [{'action': 'shell', 'resource': '*', 'effect': 'deny'}]):
            value = copy.deepcopy(self.value); value['data']['permissions'] = rules
            result = self.check(value)
            self.assertIn('permissions_sha256', result)
            self.assertNotIn('permissions', result)

    def test_session_permissions_cannot_weaken_agent_policy(self):
        cases = [None, {}, '', False,
                 [{'action': 'shell', 'resource': '*', 'effect': 'allow'}],
                 [{'action': '*', 'resource': '*', 'effect': 'ask'}],
                 [{'action': 'read', 'resource': '.env', 'effect': 'allow'}],
                 [{'action': 'edit', 'resource': '*', 'effect': 'allow'},
                  {'action': 'shell', 'resource': '*', 'effect': 'deny'}],
                 [{'action': 'shell', 'resource': '*', 'effect': 'deny', 'extra': True}],
                 [{'action': ['shell'], 'resource': '*', 'effect': 'deny'}],
                 [{'action': 'shell', 'effect': 'deny'}], [None]]
        for rules in cases:
            value = copy.deepcopy(self.value); value['data']['permissions'] = rules
            with self.subTest(rules=rules), self.assertRaises(GuardError): self.check(value)

    def test_moved_or_unverifiable_location_is_rejected(self):
        for directory in (str(self.wt.parent), '.', str(self.wt / 'missing'), None):
            value = copy.deepcopy(self.value); value['data']['location']['directory'] = directory
            with self.subTest(directory=directory), self.assertRaises(GuardError): self.check(value)

    def test_identity_agent_model_or_variant_drift_is_rejected(self):
        for key, value in [('id', 'ses_other'), ('agent', 'other'), ('model', None),
                           ('model', {'providerID': 'other', 'id': 'test-model'}),
                           ('model', {'providerID': 'openai', 'id': 'other'}),
                           ('model', {'providerID': 'openai', 'id': 'test-model', 'variant': 'high'})]:
            payload = copy.deepcopy(self.value); payload['data'][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(GuardError): self.check(payload)

    def test_missing_data_and_duplicate_json_are_rejected(self):
        for value in ({}, [], {'data': None}):
            with self.subTest(value=value), self.assertRaises(GuardError): self.check(value)
        with patch.object(adapter.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'{"data":{},"data":{}}', b'')), self.assertRaises(GuardError):
            adapter.check_session_binding(self.info, self.contract, 'ses_owned', self.wt, {})

    def test_failed_or_timed_out_metadata_query_is_fail_closed(self):
        for response in (subprocess.CompletedProcess([], 1, b'', b'private error'),
                         subprocess.CompletedProcess([], 0, b'not json', b'')):
            with patch.object(adapter.subprocess, 'run', return_value=response), self.assertRaises(GuardError):
                adapter.check_session_binding(self.info, self.contract, 'ses_owned', self.wt, {})
        with patch.object(adapter.subprocess, 'run', side_effect=subprocess.TimeoutExpired([], 5)), self.assertRaises(GuardError):
            adapter.check_session_binding(self.info, self.contract, 'ses_owned', self.wt, {})

    def test_v1_does_not_gain_an_unverified_api_dependency(self):
        with patch.object(adapter.subprocess, 'run') as run:
            self.assertIsNone(adapter.check_session_binding({'major': 1}, {}, '', self.wt, {}))
            run.assert_not_called()

    def test_invalid_session_path_never_reaches_cli(self):
        with patch.object(adapter.subprocess, 'run') as run:
            with self.assertRaises(GuardError):
                adapter.check_session_binding(self.info, self.contract, 'ses_owned/../other', self.wt, {})
            run.assert_not_called()

    def test_oversized_metadata_is_rejected(self):
        with patch.object(adapter.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b' ' * (adapter.MAX_JSON + 1), b'')), self.assertRaises(GuardError):
            adapter.check_session_binding(self.info, self.contract, 'ses_owned', self.wt, {})


class RunnerBindingTests(unittest.TestCase):
    setUp = fixture.RunnerTests.setUp
    tearDown = fixture.RunnerTests.tearDown
    git = fixture.RunnerTests.git
    call = fixture.RunnerTests.call
    init = fixture.RunnerTests.init
    state = fixture.RunnerTests.state
    run_worker = fixture.RunnerTests.run_worker

    def test_moved_resume_is_blocked_before_attempt_reservation(self):
        os.environ['MOCK_VERSION'] = '2.2.3'; self.init(); self.run_worker()
        prior = self.state(); log = Path(os.environ['MOCK_LOG']).read_bytes()
        feedback = self.root / 'feedback.txt'; feedback.write_text('Preserve first work and continue.')
        self.run_worker('session_moved', extra=('--feedback', str(feedback)), expect=3)
        self.assertEqual(self.state(), prior)
        self.assertEqual(Path(os.environ['MOCK_LOG']).read_bytes(), log)
        self.assertFalse((self.task / 'attempts/002').exists())

    def test_session_allow_resume_is_blocked_without_budget_or_execution(self):
        os.environ['MOCK_VERSION'] = '2.2.3'; self.init(); self.run_worker()
        prior = self.state(); log = Path(os.environ['MOCK_LOG']).read_bytes()
        feedback = self.root / 'feedback.txt'; feedback.write_text('Continue within policy.')
        self.run_worker('session_allow', extra=('--feedback', str(feedback)), expect=3)
        self.assertEqual(self.state(), prior)
        self.assertEqual(Path(os.environ['MOCK_LOG']).read_bytes(), log)
        self.assertFalse((self.task / 'attempts/002').exists())

    def test_post_run_session_allow_cannot_bind_completed_result(self):
        os.environ['MOCK_VERSION'] = '2.2.3'; self.init()
        self.run_worker('session_allow', expect=4)
        self.assertEqual(self.state()['status'], 'PROTOCOL_ERROR')
        self.assertIsNone(self.state()['worker_completion'])
        self.assertFalse((self.task / 'attempts/001/worker-result.json').exists())

    def test_post_run_wrong_location_cannot_bind_completed_result(self):
        os.environ['MOCK_VERSION'] = '2.2.3'; self.init()
        self.run_worker('post_session_moved', expect=4)
        state = self.state()
        self.assertEqual(state['status'], 'PROTOCOL_ERROR')
        self.assertEqual(state['attempts'], 1)
        self.assertIsNone(state['worker_completion'])
        self.assertFalse((self.task / 'attempts/001/worker-result.json').exists())

    def test_pre_query_initialization_write_blocks_before_reservation(self):
        os.environ['MOCK_VERSION'] = '2.2.3'; self.init(); self.run_worker()
        prior = self.state(); feedback = self.root / 'feedback.txt'; feedback.write_text('Continue.')
        self.run_worker('session_inspection_writes', extra=('--feedback', str(feedback)), expect=3)
        self.assertEqual(self.state(), prior)
        self.assertTrue((self.task / 'worktree/session-inspection-side-effect.txt').exists())
        self.assertFalse((self.task / 'attempts/002').exists())

    def test_post_query_initialization_write_is_policy_violation(self):
        os.environ['MOCK_VERSION'] = '2.2.3'; self.init()
        self.run_worker('session_inspection_writes', expect=4)
        self.assertEqual(self.state()['status'], 'POLICY_VIOLATION')
        self.assertIsNone(self.state()['worker_completion'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
