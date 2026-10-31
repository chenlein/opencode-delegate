"""Fail-closed readers for OpenCode 2.2.3 sources and resolved Agent.Info.

Sources are NOT an effective configuration object. Do not merge them into one.
Raw source/agent data can contain credentials and must stay in memory.
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any

from delegate_core import AGENT, MAX_LOG, require
from handoff import instruction_config_fingerprint


def decode_json(raw: bytes) -> Any:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'Duplicate configuration key; no execution', 3)
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError('Non-JSON numeric constant')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid_constant)


def jsonc_object(raw: bytes) -> dict:
    """JSONC comments/trailing commas, preserving quoted strings; no duplicates."""
    text = raw.decode('utf-8-sig')
    chars = list(text)
    i = 0
    while i < len(chars):
        if chars[i] == '"':
            i += 1
            while i < len(chars):
                if chars[i] == '\\':
                    i += 2
                elif chars[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
        elif text.startswith('//', i):
            end = text.find('\n', i + 2)
            end = len(chars) if end < 0 else end
            chars[i:end] = [' '] * (end - i)
            i = end
        elif text.startswith('/*', i):
            end = text.find('*/', i + 2)
            require(end >= 0, 'Unterminated JSONC comment; no execution', 3)
            end += 2
            chars[i:end] = ['\n' if c == '\n' else ' ' for c in chars[i:end]]
            i = end
        else:
            i += 1
    i = 0
    while i < len(chars):
        if chars[i] == '"':
            i += 1
            while i < len(chars):
                if chars[i] == '\\':
                    i += 2
                elif chars[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
        elif chars[i] == ',':
            j = i + 1
            while j < len(chars) and chars[j].isspace():
                j += 1
            if j < len(chars) and chars[j] in ']}':
                k = i - 1
                while k >= 0 and chars[k].isspace():
                    k -= 1
                require(k >= 0 and chars[k] not in '{[,:', 'Invalid JSONC trailing comma', 3)
                chars[i] = ' '
            i += 1
        else:
            i += 1
    value = decode_json(''.join(chars).encode())
    require(isinstance(value, dict), 'Configuration document must be an object; no execution', 3)
    return value


def requested_model(value: str) -> tuple[dict, dict]:
    require(isinstance(value, str) and '/' in value and '#' not in value,
            'V2 requires an explicit provider/model without an unverified variant', 3)
    provider, model = value.split('/', 1)
    require(bool(provider and model), 'Invalid V2 model identity', 3)
    return {'providerID': provider, 'model': model}, {'providerID': provider, 'id': model}


def source_snapshot(sources: Any, config: dict, wt: Path) -> dict:
    require(isinstance(sources, list) and 0 < len(sources) <= 256,
            'Unrecognized V2 configuration-source list; no execution', 3)
    expected = json.loads(json.dumps(config))
    expected['agents'][AGENT]['model'], _ = requested_model(config['agents'][AGENT]['model'])
    files, documents, inline = {}, [], []
    total = 0
    def inspect_file(path: Path, parse: bool):
        nonlocal total
        require(not path.is_symlink(), 'Symlink configuration source; no execution', 3)
        if not path.exists():
            files[str(path)] = None
            return
        require(path.is_file(), 'Configuration source is not a file; no execution', 3)
        total += path.stat().st_size
        require(total <= MAX_LOG, 'Configuration sources too large; no execution', 3)
        raw = path.read_bytes()
        files[str(path)] = hashlib.sha256(raw).hexdigest()
        if parse:
            documents.append(jsonc_object(raw))
    for entry in sources:
        require(isinstance(entry, dict), 'Malformed V2 configuration source', 3)
        kind = entry.get('type')
        if kind == 'directory':
            require(set(entry) == {'type', 'path'}, 'Unknown V2 directory-source fields', 3)
        elif kind == 'document':
            require(set(entry) in ({'type', 'info'}, {'type', 'info', 'path'}) and isinstance(entry.get('info'), dict),
                    'Unknown V2 document-source fields', 3)
            documents.append(entry['info'])
            if 'path' not in entry:
                inline.append(entry['info'])
        else:
            require(False, 'Unknown V2 configuration-source type; no execution', 3)
        if 'path' in entry:
            require(isinstance(entry['path'], str) and Path(entry['path']).is_absolute(),
                    'Nonlocal V2 configuration source; no execution', 3)
            path = Path(entry['path'])
            require(not path.is_symlink(), 'Symlink configuration source; no execution', 3)
            if kind == 'document':
                require(path.is_file(), 'Missing V2 configuration document', 3)
                inspect_file(path, False)
            else:
                require(not path.exists() or path.is_dir(), 'Invalid configuration directory', 3)
                for name in ('opencode.json', 'opencode.jsonc'):
                    inspect_file(path / name, True)
                agents = path / 'agents'
                require(not agents.is_symlink(), 'Symlink agent directory; no execution', 3)
                for agent in sorted(agents.rglob('*')) if agents.exists() else []:
                    require(not agent.is_symlink(), 'Symlink agent source; no execution', 3)
                    if agent.is_file():
                        inspect_file(agent, False)
    require(len(inline) == 1 and inline[0] == expected,
            'V2 inline policy was ignored or changed; no execution', 3)
    instruction_files = []
    for document in documents:
        # Without an effective-scalar endpoint, conflicting formatter settings
        # are deliberately rejected rather than guessing precedence.
        require('formatter' not in document or document['formatter'] is False,
                'Cannot confirm formatter is disabled in every V2 source', 3)
        require(not document.get('references'), 'V2 references need explicit instruction support; no execution', 3)
        instruction_files.extend(instruction_config_fingerprint(document, wt))
    return {'sources': sources, 'files': files, 'instruction_files': instruction_files}


def resolved_agent(agents: Any, config: dict) -> dict:
    require(isinstance(agents, list), 'Unrecognized V2 resolved-agent list', 3)
    matches = [a for a in agents if isinstance(a, dict) and (a.get('id') == AGENT or a.get('name') == AGENT)]
    require(len(matches) == 1, 'Missing or ambiguous V2 resolved agent', 3)
    actual = matches[0]
    allowed = {'id', 'name', 'description', 'mode', 'model', 'system', 'permissions', 'request', 'hidden'}
    require(set(actual) == allowed and actual['id'] == actual['name'] == AGENT,
            'Unknown V2 agent fields/identity; no execution', 3)
    expected = config['agents'][AGENT]
    _, model = requested_model(expected['model'])
    require(actual['model'] == model and all(actual[k] == expected[k] for k in ('system', 'mode', 'description')),
            'Effective custom-agent model/instructions/mode changed; no execution', 3)
    require(actual['hidden'] is False and actual['request'] == {'settings': {}, 'headers': {}, 'body': {}},
            'Unexpected V2 agent override; no execution', 3)
    rules = actual['permissions']
    require(isinstance(rules, list) and all(isinstance(r, dict) and set(r) == {'action', 'resource', 'effect'}
            and all(isinstance(v, str) for v in r.values()) and r['effect'] in ('allow', 'deny', 'ask') for r in rules),
            'Malformed V2 permission rules', 3)
    wanted = expected['permissions']
    reset = {'action': '*', 'resource': '*', 'effect': 'deny'}
    require(wanted and wanted[0] == reset, 'V2 policy must begin with universal deny', 3)
    resets = [i for i, rule in enumerate(rules) if rule == reset]
    require(bool(resets), 'V2 universal deny is missing', 3)
    tail = rules[resets[-1]:]
    # A universal deny shadows ALL earlier defaults/global rules. Preserve the
    # entire requested block in order; only further denials may follow it.
    require(tail[:len(wanted)] == wanted and all(r['effect'] == 'deny' for r in tail[len(wanted):]),
            'V2 permission rule order/content changed or extra grant; no execution', 3)
    return actual
