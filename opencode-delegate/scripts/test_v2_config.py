"""2.2.3 source-list and final-agent regressions. No real CLI/model calls."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import opencode_adapter as adapter
from delegate_core import AGENT, GuardError
from v2_config import decode_json, jsonc_object, resolved_agent, source_snapshot


def native_views(config):
    source = copy.deepcopy(config)
    provider, model = source['agents'][AGENT]['model'].split('/', 1)
    source['agents'][AGENT]['model'] = {'providerID': provider, 'model': model}
    agent = copy.deepcopy(config['agents'][AGENT])
    agent.update(id=AGENT, name=AGENT, hidden=False, model={'providerID': provider, 'id': model},
                 request={'settings': {}, 'headers': {}, 'body': {}},
                 permissions=[{'action': '*', 'resource': '*', 'effect': 'allow'}] +
                 config['permissions'] + agent['permissions'] +
                 [{'action': 'browser', 'resource': '*', 'effect': 'deny'}])
    return [{'type': 'document', 'info': source}], [agent]


def v2_replies(config):
    sources, agents = native_views(config)
    def reply(argv, **kwargs):
        if argv[1:] not in (['debug', 'config', '--standalone'], ['debug', 'agents', '--standalone']):
            raise AssertionError('Unexpected CLI command or missing private-instance flag')
        data = sources if argv[2] == 'config' else agents
        return subprocess.CompletedProcess(argv, 0, json.dumps(data).encode(), b'')
    return reply


class V2ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='v223-config-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.config, self.ak, self.pk = adapter.permission_config(
            {'model': 'openai/test-model', 'allowed_paths': ['allowed.txt'], 'protected_paths': []}, 2, self.root)
        self.sources, self.agents = native_views(self.config)

    def check(self):
        return adapter.check_effective_config({'binary': '/test/opencode'}, self.config, self.ak, self.pk, self.root, {})

    def test_native_sources_and_agent_pass_with_private_probes(self):
        with patch.object(adapter.subprocess, 'run', side_effect=v2_replies(self.config)) as run:
            self.assertEqual(len(self.check()), 64)
        self.assertEqual([call.args[0][1:] for call in run.call_args_list],
                         [['debug', 'config', '--standalone'], ['debug', 'agents', '--standalone'], ['debug', 'config', '--standalone']])

    def test_source_list_is_not_treated_as_effective_object(self):
        with self.assertRaises(GuardError): source_snapshot(self.config, self.config, self.root)

    def test_missing_or_duplicate_inline_document_rejected(self):
        for sources in ([], self.sources * 2, [{'type': 'directory', 'path': str(self.root)}]):
            with self.subTest(sources=sources), self.assertRaises(GuardError): source_snapshot(sources, self.config, self.root)

    def test_changed_inline_policy_rejected(self):
        self.sources[0]['info']['permissions'].reverse()
        with self.assertRaises(GuardError): source_snapshot(self.sources, self.config, self.root)

    def test_unknown_source_type_or_fields_rejected(self):
        for entry in ({'type': 'remote', 'path': 'https://invalid.test'}, {'type': 'directory', 'path': str(self.root), 'extra': True}):
            with self.subTest(entry=entry), self.assertRaises(GuardError): source_snapshot([entry] + self.sources, self.config, self.root)

    def test_conflicting_or_false_like_formatter_rejected(self):
        for value in (True, 0, None):
            sources = [{'type': 'document', 'path': str(self.root / 'source.json'), 'info': {'formatter': value}}] + self.sources
            (self.root / 'source.json').write_text('{}')
            with self.subTest(value=value), self.assertRaises(GuardError): source_snapshot(sources, self.config, self.root)

    def test_directory_jsonc_supports_comments_trailing_commas_and_strings(self):
        (self.root / 'opencode.jsonc').write_text('{/* note */"formatter":false,"label":"https://x/*text*/,]",// note\n}')
        result = source_snapshot([{'type': 'directory', 'path': str(self.root)}] + self.sources, self.config, self.root)
        self.assertIn(str(self.root / 'opencode.jsonc'), result['files'])

    def test_directory_formatter_cannot_be_hidden_by_inline_false(self):
        (self.root / 'opencode.json').write_text('{"formatter":true}')
        with self.assertRaises(GuardError): source_snapshot([{'type': 'directory', 'path': str(self.root)}] + self.sources, self.config, self.root)

    def test_duplicate_jsonc_keys_and_malformed_jsonc_rejected(self):
        for raw in (b'{"formatter":true,"formatter":false}', b'{/* missing', b'{"x":NaN}', b'[]', b'{,}', b'{"x":[,]}'):
            with self.subTest(raw=raw), self.assertRaises((GuardError, ValueError)): jsonc_object(raw)

    def test_duplicate_native_json_keys_rejected(self):
        with self.assertRaises(GuardError): decode_json(b'[{"type":"directory","type":"document"}]')

    def test_symlink_config_or_agent_sources_rejected(self):
        real = self.root / 'other'; real.write_text('{}')
        (self.root / 'opencode.json').symlink_to(real)
        with self.assertRaises(GuardError): source_snapshot([{'type': 'directory', 'path': str(self.root)}] + self.sources, self.config, self.root)
        (self.root / 'opencode.json').unlink()
        (self.root / 'agents').symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(GuardError): source_snapshot([{'type': 'directory', 'path': str(self.root)}] + self.sources, self.config, self.root)

    def test_unknown_instruction_references_rejected(self):
        extra = self.root / 'source.json'; extra.write_text('{}')
        sources = [{'type': 'document', 'path': str(extra), 'info': {'references': ['https://invalid.test']}}] + self.sources
        with self.assertRaises(GuardError): source_snapshot(sources, self.config, self.root)

    def test_missing_or_duplicate_resolved_agent_rejected(self):
        for agents in ([], self.agents * 2):
            with self.subTest(agents=agents), self.assertRaises(GuardError): resolved_agent(agents, self.config)

    def test_model_identity_must_match_exactly(self):
        self.agents[0]['model']['providerID'] = 'different'
        with self.assertRaises(GuardError): resolved_agent(self.agents, self.config)

    def test_prompt_mode_and_visibility_cannot_change(self):
        for key, value in [('system', 'weaker'), ('mode', 'all'), ('hidden', True)]:
            agents = copy.deepcopy(self.agents); agents[0][key] = value
            with self.subTest(key=key), self.assertRaises(GuardError): resolved_agent(agents, self.config)

    def test_request_overlays_and_unknown_agent_fields_rejected(self):
        agents = copy.deepcopy(self.agents); agents[0]['request']['headers']['Authorization'] = 'synthetic'
        with self.assertRaises(GuardError): resolved_agent(agents, self.config)
        self.agents[0]['tools'] = {'shell': True}
        with self.assertRaises(GuardError): resolved_agent(self.agents, self.config)

    def test_requested_rule_order_cannot_change(self):
        self.agents[0]['permissions'][-3], self.agents[0]['permissions'][-4] = self.agents[0]['permissions'][-4], self.agents[0]['permissions'][-3]
        with self.assertRaises(GuardError): resolved_agent(self.agents, self.config)

    def test_new_allow_or_ask_after_frozen_rules_rejected(self):
        for effect in ('allow', 'ask'):
            agents = copy.deepcopy(self.agents); agents[0]['permissions'].append({'action': 'shell', 'resource': '*', 'effect': effect})
            with self.subTest(effect=effect), self.assertRaises(GuardError): resolved_agent(agents, self.config)

    def test_missing_universal_deny_rejected(self):
        self.agents[0]['permissions'] = [r for r in self.agents[0]['permissions'] if r != {'action': '*', 'resource': '*', 'effect': 'deny'}]
        with self.assertRaises(GuardError): resolved_agent(self.agents, self.config)

    def test_additional_restrictive_native_denial_is_allowed(self):
        self.assertEqual(resolved_agent(self.agents, self.config), self.agents[0])

    def test_missing_requested_sensitive_path_denial_rejected(self):
        # Remove a denial from the final frozen block, leaving the global copy.
        rules = self.agents[0]['permissions']
        last_reset = max(i for i, rule in enumerate(rules) if rule == {'action': '*', 'resource': '*', 'effect': 'deny'})
        del rules[last_reset + 2]
        with self.assertRaises(GuardError): resolved_agent(self.agents, self.config)

    def test_malformed_permission_rules_rejected(self):
        for rule in ({'action': 'shell', 'resource': '*', 'effect': 'deny', 'extra': True},
                     {'action': 'shell', 'resource': '*', 'effect': 'unknown'},
                     {'action': 'shell', 'resource': False, 'effect': 'deny'}):
            agents = copy.deepcopy(self.agents); agents[0]['permissions'].append(rule)
            with self.subTest(rule=rule), self.assertRaises(GuardError): resolved_agent(agents, self.config)

    def test_source_drift_between_native_queries_rejected(self):
        reply = v2_replies(self.config); calls = 0
        def changed(argv, **kwargs):
            nonlocal calls
            calls += 1
            result = reply(argv, **kwargs)
            if calls == 3:
                value = json.loads(result.stdout); value.insert(0, {'type': 'directory', 'path': str(self.root)})
                result.stdout = json.dumps(value).encode()
            return result
        with patch.object(adapter.subprocess, 'run', side_effect=changed), self.assertRaises(GuardError): self.check()

    def test_directory_file_drift_even_with_unchanged_source_list_rejected(self):
        path = self.root / 'opencode.jsonc'; path.write_text('{"formatter":false}')
        sources = [{'type': 'directory', 'path': str(self.root)}] + self.sources
        before = source_snapshot(sources, self.config, self.root)
        path.write_text('{"formatter":false} // changed')
        self.assertNotEqual(before, source_snapshot(sources, self.config, self.root))

    def test_nonzero_cli_result_has_no_permissive_fallback(self):
        with patch.object(adapter.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, b'', b'failure')) as run:
            with self.assertRaises(GuardError): self.check()
        self.assertEqual(run.call_count, 1)

    def test_invalid_json_and_oversized_inspection_rejected(self):
        for raw in (b'not JSON', b' ' * (adapter.MAX_LOG + 1)):
            with self.subTest(length=len(raw)), patch.object(adapter.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, raw, b'')), self.assertRaises(GuardError): self.check()

    def test_unverified_model_variant_rejected(self):
        self.config['agents'][AGENT]['model'] += '#variant'
        with self.assertRaises(GuardError): source_snapshot(self.sources, self.config, self.root)


if __name__ == '__main__':
    unittest.main(verbosity=2)
