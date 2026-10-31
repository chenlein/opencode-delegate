"""Owned, bounded acceptance harness. Does not modify the product checkout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import threading
import time

sys.dont_write_bytecode = True

ROOT = Path(os.environ.get('MAC_ACCEPTANCE_ROOT', str(Path(__file__).resolve().parent))).resolve()
SOURCE = Path(os.environ['MAC_ACCEPTANCE_PRODUCT_CHECKOUT']).resolve()
RUNNER = SOURCE / 'opencode-delegate/scripts/delegate.py'
CODEX = Path(os.environ['MAC_ACCEPTANCE_CODEX_BINARY']).resolve()
OPENCODE = Path(os.environ['MAC_ACCEPTANCE_OPENCODE_BINARY']).resolve()
CODEX_RUNTIME_HOME = Path(os.environ.get('MAC_ACCEPTANCE_CODEX_RUNTIME_HOME', str(ROOT / 'runtime/codex-home'))).resolve()
MANIFEST = json.loads((ROOT / 'frozen-manifest.json').read_text())
sys.path.insert(0, str(RUNNER.parent))
from delegate import execute, terminate_group

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def write(p, obj):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n')

def clean_env():
    env = os.environ.copy()
    env.update(PYTHONDONTWRITEBYTECODE='1', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null', GIT_TERMINAL_PROMPT='0')
    return env

def codex_env():
    env = clean_env()
    # Fresh runtime state prevents reading/importing any pre-existing session or memory.
    # The official CLI reads the already-authorized local login through a reference;
    # no credential bytes are copied, inspected or included in evidence.
    env['CODEX_HOME'] = str(CODEX_RUNTIME_HOME)
    for k in ['CODEX_APP_TOOLS_PIPE_PATH', 'CODEX_INTERNAL_ORIGINATOR_OVERRIDE', 'CODEX_SESSION_ID',
              'CODEX_THREAD_ID', 'CODEX_TOOL_CALL_ID', 'CODEX_SAGE_BACKFILL_TRACKER_TAB_REUSE']:
        env.pop(k, None)
    return env

def reserve(kind, label):
    p = ROOT / 'ledger.json'
    ledger = json.loads(p.read_text())
    used = ledger['coordination_session'] + len(ledger['entries'])
    if used >= ledger['limit']:
        raise RuntimeError('Logical model budget exhausted before ' + label)
    ledger['entries'].append({'ordinal': used + 1, 'kind': kind, 'label': label, 'reserved_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
    write(p, ledger)
    print(json.dumps({'budget_reserved': used + 1, 'label': label}), flush=True)

def guard_config():
    paths = [Path.home() / '.codex/config.toml', Path.home() / '.config/opencode/opencode.json', Path.home() / '.config/opencode/opencode.jsonc']
    # Content is never printed or sent to a model. Only change-detection digests.
    return {str(p): sha(p) if p.is_file() else None for p in paths}

def source_snapshot(repo):
    result = {}
    for p in repo.rglob('*'):
        if '.git' in p.relative_to(repo).parts:
            continue
        if p.is_file():
            result[p.relative_to(repo).as_posix()] = sha(p)
        elif p.is_symlink():
            raise RuntimeError('Unexpected source symlink')
    return result

def check_snapshot(repo, implementation=False):
    actual = source_snapshot(repo)
    changed = sorted(k for k in set(actual) | set(MANIFEST['files']) if actual.get(k) != MANIFEST['files'].get(k))
    return {'files': actual, 'changed': changed, 'scope_ok': changed == ['src/arithmetic.py'] if implementation else not changed,
            'protected_ok': all(actual.get(k) == v for k, v in MANIFEST['files'].items() if k != 'src/arithmetic.py')}

def run_fixed(repo, evidence_root):
    evidence = evidence_root / 'verification' / str(time.time_ns())
    evidence.mkdir(parents=True)
    result = []
    for name, argv in [('business', [sys.executable, 'checks/acceptance.py']), ('gate', [sys.executable, 'checks/gate.py', str(evidence)])]:
        proc = subprocess.run(argv, cwd=repo, env=clean_env(), capture_output=True, text=True, timeout=10)
        (evidence / (name + '.out')).write_text(proc.stdout)
        (evidence / (name + '.err')).write_text(proc.stderr)
        result.append({'id': name, 'exit_code': proc.returncode, 'stdout': proc.stdout, 'stderr': proc.stderr,
                       'stdout_sha256': hashlib.sha256(proc.stdout.encode()).hexdigest(), 'stderr_sha256': hashlib.sha256(proc.stderr.encode()).hexdigest()})
    return {'checks': result, 'snapshot': check_snapshot(repo, True), 'all_passed': all(x['exit_code'] == 0 for x in result)}

def runner_env():
    env = clean_env()
    # Isolate rule/config/cache discovery, retain OpenCode's own pre-existing local auth store.
    # No authentication file is copied or inspected.
    env.update(CODEX_HOME=str(ROOT / 'runtime/runner-codex-home'), XDG_CONFIG_HOME=str(ROOT / 'runtime/opencode-config'),
               XDG_CACHE_HOME=str(ROOT / 'runtime/opencode-cache'), XDG_STATE_HOME=str(ROOT / 'runtime/opencode-state'),
               OPENCODE_PURE='1', OPENCODE_DISABLE_AUTOUPDATE='1', OPENCODE_DISABLE_DEFAULT_PLUGINS='1',
               OPENCODE_DISABLE_EXTERNAL_SKILLS='1', OPENCODE_DISABLE_CLAUDE_CODE='1')
    return env

def doctor():
    proc = subprocess.run([sys.executable, str(RUNNER), 'doctor', '--opencode', str(OPENCODE)], cwd=ROOT,
                          env=runner_env(), capture_output=True, text=True, timeout=45)
    (ROOT / 'private/doctor.out').write_text(proc.stdout)
    (ROOT / 'private/doctor.err').write_text(proc.stderr)
    if proc.returncode:
        raise RuntimeError('OpenCode doctor failed: ' + proc.stderr[-1000:])
    obj = json.loads(proc.stdout)
    write(ROOT / 'doctor.json', obj)
    print(json.dumps({'doctor': obj['version'], 'binary_sha256': obj['binary_sha256']}), flush=True)
    return obj

def prepare_contracts():
    base = json.loads((SOURCE / 'opencode-delegate/assets/task.template.json').read_text())
    for case in ['readonly', 'fix']:
        c = dict(base)
        c.update(project_id='mac-three-route', task_id=case, environment='macos-owned-synthetic-acceptance', repo=str(ROOT / 'fixtures/skill'),
                 model='openai/gpt-6.1-sol', timeout_seconds=45, max_attempts=2 if case == 'fix' else 1, max_execution_seconds=90 if case == 'fix' else 45,
                 protected_paths=['AGENTS.md', 'checks/', 'protected/', 'src/catalog.py', 'src/basket.py', 'README.md', '.gitignore', 'src/__init__.py'],
                 verification_sources=['checks/'], instruction_sources=[], context=[{'path': 'AGENTS.md', 'purpose': 'Frozen fixture boundaries', 'kind': 'rule'},
                    {'path': 'src/basket.py', 'purpose': 'Read basket flow', 'kind': 'reference'}, {'path': 'src/catalog.py', 'purpose': 'Read trace marker and prices', 'kind': 'reference'},
                    {'path': 'src/arithmetic.py', 'purpose': 'Analyze numeric combination', 'kind': 'reference'}])
        if case == 'readonly':
            c.update(mode='analyze', allowed_paths=[], objective='Read src/catalog.py, src/basket.py and src/arithmetic.py. Report the exact TRACE_MARKER, cite source paths, and explain how basket.total combines prices and signed adjustment. Do not edit or run tests.',
                     acceptance=[{'id': 'A1', 'description': 'Exact catalogue trace marker and source citations; accurate basket call flow.'}], checks=[])
        else:
            c.update(mode='implement', allowed_paths=['src/arithmetic.py'], objective='Fix add so it returns the numeric sum. Edit only src/arithmetic.py; preserve all protected files and the public API. The four frozen arithmetic assertions and three basket integration assertions must pass. Do not run tests yourself. If later feedback describes a transient verifier failure, preserve the accepted first edit and continue the same session.',
                     acceptance=[{'id': 'A1', 'description': 'Four arithmetic assertions and three basket integration assertions pass with correct sum semantics.'},
                                 {'id': 'A2', 'description': 'Only src/arithmetic.py changes; all protected files and rules stay byte-identical.'},
                                 {'id': 'A3', 'description': 'Controlled transient verifier failure is retained, then same-session incremental continuation passes unchanged fixed gate.'}],
                     checks=[{'id': 'business', 'argv': ['{python}', 'checks/acceptance.py'], 'cwd': '.', 'timeout_seconds': 10, 'criterion_ids': ['A1', 'A2'], 'output_contains': ['ASSERTIONS_OK']},
                             {'id': 'gate', 'argv': ['{python}', 'checks/gate.py', '{evidence_dir}'], 'cwd': '.', 'timeout_seconds': 10, 'criterion_ids': ['A3'], 'output_contains': ['CONTROLLED_GATE_OK']}])
        write(ROOT / ('contract-' + case + '.json'), c)

class DelegateTool:
    def __init__(self, route_dir):
        self.tasks = {}
        self.route_dir = route_dir
        self.sequence = 0
        self.info = json.loads((ROOT / 'doctor.json').read_text())

    def __call__(self, args):
        self.sequence += 1
        case, action = args.get('case'), args.get('action')
        if case not in ['readonly', 'fix']:
            raise RuntimeError('Unknown frozen case')
        if action == 'contract':
            return json.loads((ROOT / ('contract-' + case + '.json')).read_text())
        if action == 'init':
            if case in self.tasks:
                raise RuntimeError('Task already exists; reuse exact task/session')
            argv = ['init', '--contract', str(ROOT / ('contract-' + case + '.json')), '--state-root', str(self.route_dir / 'runner-state')]
            if case == 'fix': argv.append('--authorize-implementation')
        else:
            if case not in self.tasks:
                raise RuntimeError('Initialize frozen task first')
            task = self.tasks[case]
            argv = [action, '--task', str(task)]
            if action == 'run':
                reserve('opencode-worker', case + '-run')
                argv += ['--opencode', str(OPENCODE), '--acknowledge-local-execution', '--experimental-cli-version', self.info['version']]
                if case == 'fix': argv.append('--authorize-implementation')
                feedback = args.get('feedback')
                if feedback:
                    p = self.route_dir / ('feedback-' + str(self.sequence) + '.md')
                    p.write_text(feedback + '\n')
                    argv += ['--feedback', str(p)]
            elif action == 'verify': argv += ['--authorize-tests']
            elif action == 'review':
                state = json.loads((task / 'state.json').read_text())
                review = {'task_id': state['task_id'], 'contract_sha256': state['contract_sha256'], 'snapshot_sha256': state['checkpoint_sha256'],
                          'verification_sha256': state['verification']['sha256'], 'decision': args.get('decision', 'needs_fix'),
                          'reviewer': 'codex-live-coordinator', 'criteria': args.get('criteria', []), 'rationale': args.get('rationale', '')}
                p = self.route_dir / ('review-' + str(self.sequence) + '.json')
                write(p, review)
                argv += ['--review', str(p)]
            elif action == 'inspect':
                return self.inspect(case)
            elif action not in ['status', 'failure']:
                raise RuntimeError('Action outside bounded runner adapter')
        out = self.route_dir / ('runner-' + str(self.sequence) + '.out')
        err = self.route_dir / ('runner-' + str(self.sequence) + '.err')
        result = execute([sys.executable, str(RUNNER), *argv], ROOT, runner_env(), 95, out, err)
        text = out.read_text()
        if action == 'init' and result['exit_code'] == 0:
            self.tasks[case] = Path(json.loads(text)['task_dir'])
            write(self.route_dir / 'tasks.json', {k: str(v) for k, v in self.tasks.items()})
        record = {'action': action, 'case': case, 'execution': result, 'stdout': text, 'stderr': err.read_text()}
        if case in self.tasks:
            record['current'] = self.inspect(case)
        write(self.route_dir / ('runner-' + str(self.sequence) + '.json'), record)
        print(json.dumps({'delegate_action': action, 'case': case, 'exit': result['exit_code'], 'status': record.get('current', {}).get('status')}), flush=True)
        return record

    def inspect(self, case):
        task = self.tasks[case]
        state = json.loads((task / 'state.json').read_text())
        out = {'status': state['status'], 'task_id': state['task_id'], 'session_id': state['session_id'], 'attempts': state['attempts'],
               'contract_sha256': state['contract_sha256'], 'checkpoint_sha256': state['checkpoint_sha256'], 'worktree': state['worktree'],
               'snapshot': check_snapshot(Path(state['worktree']), case == 'fix')}
        for p in ['src/arithmetic.py', 'src/catalog.py', 'src/basket.py']:
            out[p] = (Path(state['worktree']) / p).read_text()
        if state.get('verification'):
            v = json.loads((task / state['verification']['path']).read_text())
            out['verification'] = v
            directory = (task / state['verification']['path']).parent
            out['check_outputs'] = {p.name: p.read_text() for p in directory.glob('*.log')}
            patch = directory / 'tracked.patch'
            out['tracked_patch'] = patch.read_text() if patch.is_file() else None
        for p in sorted((task / 'attempts').glob('*/worker-result.json')) if (task / 'attempts').exists() else []:
            out.setdefault('worker_results', []).append(json.loads(p.read_text()))
        return out

class Server:
    def __init__(self, route, directory, dynamic=None):
        self.route, self.directory, self.dynamic = route, directory, dynamic
        self.q, self.nextid, self.pending = queue.Queue(), 0, {}
        self.events, self.threads, self.usage, self.completed_items = [], {}, {}, []
        self.child_turn_items = set()
        config = {'project_doc_max_bytes': 0, 'sqlite_home': str(CODEX_RUNTIME_HOME / 'state'), 'log_dir': str(ROOT / 'runtime/codex-log'),
                  'web_search': 'disabled', 'model_reasoning_effort': 'medium', 'agents.max_depth': 1,
                  'agents.max_concurrent_threads_per_session': 2, 'features.memories': False, 'features.hooks': False,
                  'features.apps': False, 'features.plugins': False, 'features.skip_host_skill_discovery': True,
                  'features.shell_snapshot': False, 'features.system_proxy_fallback': False}
        self.config = config
        argv = [str(CODEX)]
        for k, v in config.items():
            argv += ['-c', k + '=' + json.dumps(v)]
        # Prevent MCP startup without revealing or using any configured server values.
        cp = CODEX_RUNTIME_HOME / 'config.toml'
        if cp.is_file():
            for name in re.findall(r'^\s*\[mcp_servers\.([A-Za-z0-9_-]+)\]\s*$', cp.read_text(), re.M):
                argv += ['-c', 'mcp_servers.' + name + '.enabled=false']
        argv += ['app-server', '--listen', 'stdio://']
        self.err = (directory / 'server.err').open('wb')
        self.process = subprocess.Popen(argv, cwd=ROOT, env=codex_env(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=self.err, text=True, bufsize=1, start_new_session=True)
        write(directory / 'process.json', {'pid': self.process.pid, 'argv': argv, 'started_at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
        def reader():
            for line in self.process.stdout:
                try: self.q.put(json.loads(line))
                except Exception: self.q.put({'unparsed': line})
            self.q.put({'eof': True})
        threading.Thread(target=reader, daemon=True).start()
        self.nextid += 1
        rid = self.nextid
        self.send({'id': rid, 'method': 'initialize', 'params': {'clientInfo': {'name': 'mac_acceptance_harness', 'title': 'Owned synthetic acceptance', 'version': '1'},
                                'capabilities': {'experimentalApi': True, 'requestAttestation': False, 'explicitGatewayOauth': True}}})
        self.send({'method': 'initialized', 'params': {}})
        try:
            deadline = time.monotonic() + 30
            while rid not in self.pending:
                self.receive(deadline)
            response = self.pending.pop(rid)
            if 'error' in response:
                raise RuntimeError('initialize: ' + json.dumps(response['error']))
        except Exception:
            self.stop()
            reserve('failed-startup', route + '-initialize-failure')
            raise

    def send(self, obj):
        self.process.stdin.write(json.dumps(obj) + '\n')
        self.process.stdin.flush()

    def handle(self, ev):
        self.events.append(ev)
        with (self.directory / 'events.jsonl').open('a') as f: f.write(json.dumps(ev) + '\n')
        method, p = ev.get('method'), ev.get('params', {})
        if 'id' in ev and 'method' not in ev:
            self.pending[ev['id']] = ev
        if method == 'thread/started':
            t = p['thread']; self.threads[t['id']] = t
            print(json.dumps({'thread_started': t['id'], 'parent': t.get('parentThreadId'), 'model': t.get('model'), 'effort': t.get('reasoningEffort')}), flush=True)
        if method == 'thread/tokenUsage/updated':
            self.usage[p['threadId']] = p
            write(self.directory / 'usage.json', self.usage)
        if method == 'item/completed':
            self.completed_items.append(p)
            item = p.get('item', {})
            if item.get('type') == 'collabAgentToolCall':
                print(json.dumps({'collaboration': item}), flush=True)
                # Rejoin only a child just created by this owned parent so its native
                # token notifications can be observed. This sends no model turn.
                if item.get('tool') == 'spawnAgent':
                    for child in item.get('receiverThreadIds', []):
                        try:
                            metadata = self.rpc('thread/resume', {'threadId': child, 'excludeTurns': True}, 10)
                            self.threads[child] = metadata['thread']
                            write(self.directory / ('child-' + child + '-metadata.json'), metadata)
                        except Exception as e:
                            write(self.directory / ('child-' + child + '-subscription.json'), {'supported': False, 'reason': str(e), 'usage': 'UNKNOWN'})
        if method == 'item/tool/call':
            if not self.dynamic or p.get('tool') != 'delegate_action':
                result = {'contentItems': [{'type': 'inputText', 'text': 'Tool unavailable'}], 'success': False}
            else:
                try:
                    obj = self.dynamic(p['arguments'])
                    result = {'contentItems': [{'type': 'inputText', 'text': json.dumps(obj)}], 'success': True}
                except Exception as e:
                    result = {'contentItems': [{'type': 'inputText', 'text': str(e)}], 'success': False}
            self.send({'id': ev['id'], 'result': result})
        elif 'id' in ev and method:
            # Never grant an approval, authentication action, or arbitrary client request.
            self.send({'id': ev['id'], 'error': {'code': -32000, 'message': 'This acceptance harness cannot approve or authenticate new actions'}})
        if ev.get('eof'):
            raise RuntimeError('Owned app-server exited')

    def receive(self, deadline):
        if time.monotonic() > deadline: raise TimeoutError('Bounded app-server wait expired')
        try: self.handle(self.q.get(timeout=min(1, max(.01, deadline - time.monotonic()))))
        except queue.Empty: pass

    def rpc(self, method, params, timeout=30):
        self.nextid += 1; rid = self.nextid
        self.send({'id': rid, 'method': method, 'params': params})
        deadline = time.monotonic() + timeout
        while rid not in self.pending: self.receive(deadline)
        ev = self.pending.pop(rid)
        if 'error' in ev: raise RuntimeError(method + ': ' + json.dumps(ev['error']))
        return ev.get('result')

    def start(self, repo, dynamic=False):
        params = {'cwd': str(repo), 'runtimeWorkspaceRoots': [str(repo)], 'model': 'gpt-6.1-sol', 'modelProvider': 'openai',
                  'approvalPolicy': 'never', 'sandbox': 'workspace-write', 'ephemeral': True, 'config': self.config,
                  'developerInstructions': 'This is an authorized synthetic acceptance run. Use only the provided fixture and explicit skill paths. Never read private memories, old sessions, credentials, or unrelated projects. Never change global configuration, Git history/index, tests, rules or protected files. No new authentication, network, commits, pushes, or permission escalation. Do not write bytecode. Do not spawn subagents unless the route explicitly requires exactly one. Keep final reports concise and evidence-based.'}
        if dynamic:
            params['dynamicTools'] = [{'type': 'function', 'name': 'delegate_action', 'description': 'Bounded adapter to the real unchanged opencode-delegate runner. Frozen contracts, existing local OpenCode authentication, exact task binding, independent fixed checks. No arbitrary shell. Actions contract/init/run/verify/inspect/review/status/failure. A run consumes one model budget reservation.',
                'inputSchema': {'type': 'object', 'properties': {'case': {'type': 'string', 'enum': ['readonly', 'fix']},
                    'action': {'type': 'string', 'enum': ['contract', 'init', 'run', 'verify', 'inspect', 'review', 'status', 'failure']},
                    'feedback': {'type': 'string'}, 'decision': {'type': 'string', 'enum': ['accept', 'needs_fix', 'reject']},
                    'criteria': {'type': 'array', 'items': {'type': 'object'}}, 'rationale': {'type': 'string'}}, 'required': ['case', 'action'], 'additionalProperties': False}}]
        obj = self.rpc('thread/start', params)
        write(self.directory / 'thread-start.json', obj)
        if obj.get('instructionSources'):
            raise RuntimeError('Unexpected ambient instruction sources; do not send model a turn')
        if obj.get('sandbox', {}).get('type') != 'workspaceWrite':
            raise RuntimeError('Normal workspace-write sandbox was not retained')
        return obj['thread']['id']

    def turn(self, tid, stage, prompt):
        reserve('codex-coordinator' if self.route in ['native', 'skill'] else 'codex-direct', self.route + '-' + stage)
        if self.route == 'native': reserve('codex-native-child-reservation', 'native-' + stage + '-one-child-turn')
        start = time.monotonic()
        write(self.directory / (stage + '-prompt.json'), {'thread_id': tid, 'text': prompt})
        obj = self.rpc('turn/start', {'threadId': tid, 'input': [{'type': 'text', 'text': prompt, 'text_elements': []}],
                                    'model': 'gpt-6.1-sol', 'effort': 'medium'}, 30)
        turnid = obj['turn']['id']
        deadline = start + 75
        try:
            while True:
                for ev in reversed(self.events):
                    if ev.get('method') == 'turn/completed' and ev['params'].get('threadId') == tid and ev['params']['turn']['id'] == turnid:
                        done = ev['params']['turn']
                        items = [x['item'] for x in self.completed_items if x.get('threadId') == tid and x.get('turnId') == turnid]
                        messages = [x.get('text', '') for x in items if x.get('type') == 'agentMessage']
                        result = {'thread_id': tid, 'turn_id': turnid, 'status': done['status'], 'error': done.get('error'),
                                  'wall_seconds': time.monotonic() - start, 'messages': messages, 'usage': self.usage.get(tid, 'UNKNOWN')}
                        write(self.directory / (stage + '-result.json'), result)
                        print(json.dumps({'route': self.route, 'stage': stage, 'status': done['status'], 'wall_seconds': result['wall_seconds'], 'messages': messages}), flush=True)
                        if done['status'] != 'completed': raise RuntimeError('Model turn did not complete: ' + json.dumps(done.get('error')))
                        return result
                self.receive(deadline)
        except TimeoutError:
            self.rpc('turn/interrupt', {'threadId': tid, 'turnId': turnid}, 10)
            raise

    def stop(self):
        try: self.process.stdin.close()
        except Exception: pass
        try: self.process.wait(timeout=3)
        except subprocess.TimeoutExpired: pass
        cleanup = terminate_group(self.process)
        self.err.close()
        write(self.directory / 'cleanup.json', cleanup)
        write(self.directory / 'threads.json', self.threads)
        write(self.directory / 'usage.json', self.usage)
        print(json.dumps({'server_cleanup': cleanup}), flush=True)
        return cleanup

def route_prompts(route, repo):
    common = 'Frozen baseline ' + MANIFEST['source_commit'] + '. Fixture rules: ' + (repo / 'AGENTS.md').read_text()
    readonly = common + '\nStage 1, read-only: inspect src/catalog.py, src/basket.py and src/arithmetic.py. Report the exact TRACE_MARKER with source paths and explain how basket.total combines prices and signed adjustment. Change no files and run no tests. Do not solve stage 2 yet.'
    fix = 'Stage 2: implementation is now authorized only in src/arithmetic.py. Fix add to return the numeric sum while preserving its API. Four frozen arithmetic assertions (2,3)=5, (-2,3)=1, (0,0)=0, (-2,-3)=-5 and three frozen basket integration assertions must pass. All other files, checks and rules are protected. Do not run tests yourself; the independent verifier will provide results. Do not commit or edit Git state.'
    feedback = 'Stage 3, incremental feedback from the independent frozen verifier: business check exit 0, all four arithmetic and three basket assertions passed; gate check exit 5, CONTROLLED_TRANSIENT_FAILURE. This gate intentionally fails once to exercise recovery; it is not evidence of a remaining code defect. Preserve the first implementation bytes and all protections. Continue this exact task/session, assess the evidence and return for a full rerun of the same fixed checks. Do not run tests or make an unnecessary edit.'
    if route == 'native':
        readonly += '\nRoute requirement: spawn exactly ONE native Codex subagent for this bounded read-only stage, with no forked conversation context and the SAME gpt-6.1-sol / medium settings. Give only this fixture brief. Wait for it; do not do its source analysis yourself. Keep that child available for the next two stages; report its id and marker. Never spawn another child.'
        fix += '\nUse send_message/follow-up on the SAME existing child. No new child, no parent source edit. Forward only this incremental brief, wait and report the result and child id. One child turn only.'
        feedback += '\nSend only this incremental feedback to the SAME child; wait and report its response. One child turn only, no new subagent.'
    if route == 'skill':
        intro = '$opencode-delegate is explicitly invoked. Read ' + str(SOURCE / 'opencode-delegate/SKILL.md') + ' and its protocol/recovery references. Use delegate_action, a bounded host adapter invoking the real unchanged runner under the authorized local environment. Contracts/checks are already frozen: inspect them, do not rewrite them. No native subagents or direct source edits. OpenCode uses only its own existing local authentication. Exact version is ' + json.loads((ROOT / 'doctor.json').read_text())['version'] + '. '
        readonly = intro + common + '\nStage 1: get readonly contract, initialize it, run it once, inspect result/source, verify and review every criterion from actual evidence. Analysis must be accurate, exact marker/citations and source unchanged. Review JSON uses decision "accept", result "pass", evidence ["diff", "file:src/catalog.py", "file:src/basket.py"] if actually justified. If blocked, report it. Do not initialize or run fix yet.'
        fix = 'Stage 2: inspect frozen fix contract, initialize it, run exactly once. Do not edit source yourself. Inspect the worker output and run the frozen independent verifier. This may return NEEDS_FIX; preserve and report all results, do not start a second run in this turn and do not accept on worker claims alone.'
        feedback = 'Stage 3: inspect current fix evidence first. The frozen verifier intentionally injected exactly one transient gate failure while business assertions passed; this is not a worker code defect. Use run on the SAME registered task/session with only this incremental feedback, preserving the first edit and all protected files. Exactly one worker continuation is allowed. Then run the SAME frozen verify checks, inspect actual source/diff and all acceptance criteria, and review with decision "accept" only if all criteria are independently supported. For passes use evidence test:business for A1/A2, diff for A2, test:gate for A3; explain same-session binding and preserved first edit. Never change the verifier or threshold.'
    return readonly, fix, feedback

def run_route(route):
    directory = ROOT / 'private' / route
    directory.mkdir(exist_ok=False)
    before = guard_config()
    repo = ROOT / 'fixtures' / route
    delegate = DelegateTool(directory) if route == 'skill' else None
    server = None
    report = {'route': route, 'source_commit': MANIFEST['source_commit'], 'requested_model': 'gpt-6.1-sol', 'requested_effort': 'medium',
              'provider_snapshot': 'UNKNOWN', 'coordinator_outer_usage': 'UNKNOWN', 'start_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'clock_boundary': 'Before app-server launch/thread setup through independent final verification, review and owned process cleanup', 'stages': []}
    start = time.monotonic()
    try:
        server = Server(route, directory, delegate)
        tid = server.start(repo, bool(delegate))
        prompts = route_prompts(route, repo)
        readonly = server.turn(tid, 'readonly', prompts[0]); report['stages'].append(readonly)
        text = '\n'.join(readonly['messages'])
        if route == 'skill':
            info = delegate.inspect('readonly')
            readonly_snapshot = info['snapshot']
            # Worker output remains in owned task evidence; not inherited by other routes.
            alltext = json.dumps(info)
            report['readonly_native_status'] = info['status']
        else:
            readonly_snapshot = check_snapshot(repo)
            alltext = text
        report['readonly_verified'] = readonly_snapshot['scope_ok'] and MANIFEST['marker'] in alltext and 'src/catalog.py' in alltext and 'src/basket.py' in alltext
        report['readonly_snapshot'] = readonly_snapshot
        if not report['readonly_verified']: raise RuntimeError('Read-only semantic/unchanged-source acceptance failed')
        fixed = server.turn(tid, 'fix', prompts[1]); report['stages'].append(fixed)
        if route == 'skill':
            info = delegate.inspect('fix'); target = Path(info['worktree'])
            report['first_verify'] = info
        else:
            target = repo
            report['first_verify'] = run_fixed(target, directory)
        report['first_edit_sha256'] = sha(target / 'src/arithmetic.py')
        resumed = server.turn(tid, 'resume', prompts[2]); report['stages'].append(resumed)
        if route == 'skill':
            final = delegate.inspect('fix')
            report['final_verify'] = final
            passed = final['status'] == 'ACCEPTED' and final['snapshot']['scope_ok'] and final['snapshot']['protected_ok']
        else:
            final = run_fixed(target, directory)
            report['final_verify'] = final
            passed = final['all_passed'] and final['snapshot']['scope_ok'] and final['snapshot']['protected_ok']
        report['final_edit_sha256'] = sha(target / 'src/arithmetic.py')
        report['first_edit_preserved'] = report['first_edit_sha256'] == report['final_edit_sha256']
        report['final_source'] = (target / 'src/arithmetic.py').read_text()
        report['status'] = 'PASS' if passed and report['first_edit_preserved'] else 'FAIL'
    except Exception as e:
        report['status'] = 'BLOCKED'
        report['blocker'] = {'action': 'three-route ' + route + ' acceptance', 'target': 'owned synthetic fixture', 'reason': str(e),
                             'outcome': 'See captured events and source snapshot; not treated as success'}
        print(json.dumps({'route': route, 'blocker': str(e)}), flush=True)
    finally:
        if server:
            report['cleanup'] = server.stop()
            report['thread_usage'] = server.usage
            report['threads'] = server.threads
        report['end_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
        report['end_to_end_wall_seconds'] = time.monotonic() - start
        after = guard_config()
        report['global_configuration_unchanged'] = before == after
        report['global_configuration_before'] = before
        report['global_configuration_after'] = after
        report['source_snapshot_at_end'] = check_snapshot(repo, route != 'skill')
        write(directory / 'report.json', report)
        print(json.dumps({'route': route, 'status': report['status'], 'e2e': report['end_to_end_wall_seconds'], 'global_config_unchanged': before == after}), flush=True)

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=['doctor', 'prepare-contracts', 'direct', 'native', 'skill'])
    a = p.parse_args()
    if a.action == 'doctor': doctor()
    elif a.action == 'prepare-contracts': prepare_contracts()
    else: run_route(a.action)
