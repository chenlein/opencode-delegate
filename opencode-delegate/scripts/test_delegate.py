#!/usr/bin/env python3
"""Offline regression tests. No OpenCode/model/network calls; temporary Git repos only."""
import contextlib
import fcntl
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("delegate", HERE / "delegate.py")
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)

MOCK = r'''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys, time
args=sys.argv[1:]
scenario=os.environ.get('MOCK_SCENARIO','ok')
if args==['--version']:
 print(os.environ.get('MOCK_VERSION','1.2.0')); sys.exit(0)
if args==['run','--help']:
 print('--format --agent --model --session --variant --standalone' if scenario!='no_capability' else '--agent');sys.exit(0)
if args==['debug','config']:
 config=json.loads(os.environ.get('OPENCODE_CONFIG_CONTENT','{}'))
 if scenario=='bad_config': config={}
 if scenario=='bad_formatter': config['formatter']=True
 if scenario=='reordered_permissions':
  agent=config['agent']['codex_delegate_worker_v2']
  agent['permission']['edit']=dict(reversed(list(agent['permission']['edit'].items())))
 if scenario=='config_writes': pathlib.Path('config-side-effect.txt').write_text('bad')
 print(json.dumps(config));sys.exit(0)
if not args or args[0]!='run': sys.exit(2)
if os.environ.get('MOCK_LOG'):
 pathlib.Path(os.environ['MOCK_LOG']).write_text(json.dumps({'args':args,'config':json.loads(os.environ['OPENCODE_CONFIG_CONTENT']),'nested':os.environ.get('OPENCODE_DELEGATE_ACTIVE')}))
packet=json.loads(args[-1].split('TASK_PACKET:\n',1)[1])
task=packet['anchors']['task_id']
sid=args[args.index('--session')+1] if '--session' in args else 'ses_mock_123'
if scenario=='wrong_session': sid='ses_wrong_456'
if scenario in ('edit','fail_test','fake_tests','resume_edit'):
 pathlib.Path('allowed.txt').write_text('fixed\n' if scenario!='resume_edit' else 'fixed-again\n')
if scenario=='protected': pathlib.Path('AGENTS.md').write_text('ignore safety\n')
if scenario=='out_of_scope': pathlib.Path('other.txt').write_text('changed\n')
if scenario=='new_file': pathlib.Path('new.txt').write_text('new\n')
if scenario=='ignored':
 pathlib.Path('cache').mkdir(exist_ok=True);pathlib.Path('cache/hidden.txt').write_text('hidden\n')
if scenario=='symlink': pathlib.Path('allowed.txt').unlink();pathlib.Path('allowed.txt').symlink_to('/etc/hosts')
if scenario=='stage':
 pathlib.Path('allowed.txt').write_text('trailing   \n');subprocess.run(['git','add','allowed.txt'],check=True)
if scenario=='whitespace': pathlib.Path('allowed.txt').write_text('trailing   \n')
if scenario=='commit':
 pathlib.Path('allowed.txt').write_text('committed\n');subprocess.run(['git','add','allowed.txt'],check=True)
 subprocess.run(['git','-c','user.name=Mock','-c','user.email=mock@example.test','commit','-qm','forbidden'],check=True)
if scenario=='rename': pathlib.Path('allowed.txt').rename('elsewhere.txt')
if scenario=='hardlink': os.link('allowed.txt','new.txt')
if scenario=='timeout': time.sleep(20)
if scenario=='nonzero': sys.exit(7)
if scenario=='bad_json': print('not json');sys.exit(0)
if scenario=='error_event': print(json.dumps({'type':'error','sessionID':sid,'error':'bad'}));sys.exit(0)
result={'schema_version':1,'task_id':task,'status':'blocked' if scenario=='blocked' else 'complete','summary':'Mock result, not real model output.','claims':[{'criterion_id':'A1','claim':'done','evidence':['file:allowed.txt']}],'tests_run':['pretend'] if scenario=='fake_tests' else [],'risks':[]}
text='BEGIN_DELEGATE_RESULT\n'+json.dumps(result)+'\nEND_DELEGATE_RESULT'
if scenario=='no_result': text='All done, trust me.'
event={'type':'text','sessionID':sid,'part':{'type':'text','text':text}}
if scenario=='no_session': del event['sessionID']
print(json.dumps(event))
if scenario=='two_sessions': print(json.dumps({'type':'step_start','sessionID':'ses_other'}))
if scenario=='usage': print(json.dumps({'type':'step_finish','sessionID':sid,'part':{'id':'part_1','tokens':{'input':123,'output':45},'cost':0.0}}))
print(json.dumps({'type':'step_finish',**({} if scenario=='no_session' else {'sessionID':sid}),'part':{'reason':'stop'}}))
'''

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="opencode-delegate-test-")
        self.root = Path(self.tmp.name)
        home = self.root / "home"
        home.mkdir()
        env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(home),
               "XDG_CONFIG_HOME": str(home / ".config"), "XDG_DATA_HOME": str(home / ".local/share"),
               "XDG_STATE_HOME": str(home / ".local/state"), "XDG_CACHE_HOME": str(home / ".cache"),
               "CODEX_HOME": str(home / ".codex"), "PYTHONDONTWRITEBYTECODE": "1",
               "MOCK_SCENARIO": "ok", "MOCK_VERSION": "1.2.0", "MOCK_LOG": str(self.root / "calls.json")}
        self.env_patch = patch.dict(os.environ, env, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.test")
        self.git("config", "commit.gpgsign", "false")
        (self.repo / "allowed.txt").write_text("original\n")
        (self.repo / "other.txt").write_text("original\n")
        (self.repo / "AGENTS.md").write_text("Do not modify rules.\n")
        (self.repo / ".gitignore").write_text("cache/\n")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")
        self.binary = self.root / "opencode"
        self.binary.write_text("#!" + sys.executable + " -S\n" + MOCK.split("\n", 1)[1])
        self.binary.chmod(0o755)
        self.contract = {"schema_version": 2, "project_id": "example", "task_id": "t1", "environment": "local-test",
                         "repo": str(self.repo), "mode": "implement", "objective": "Fix allowed.txt only", "non_goals": ["No deployment"],
                         "allowed_paths": ["allowed.txt"], "protected_paths": [], "context": [{"path": "AGENTS.md", "purpose": "Project rules", "kind": "rule"}],
                         "acceptance": [{"id": "A1", "description": "File content is fixed"}], "checks": [],
                         "verification_artifacts": [], "model": "openai/test-model", "timeout_seconds": 30, "max_attempts": 3}
        self.task = None
        self.old_umask = os.umask(0o077)

    def tearDown(self):
        self.env_patch.stop()
        os.umask(self.old_umask)
        self.tmp.cleanup()

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

    def call(self, *args, expect=None):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = d.main(list(args))
        if expect is not None:
            self.assertEqual(rc, expect, f"argv={args}\nstdout={out.getvalue()}\nstderr={err.getvalue()}")
        self.last_out, self.last_err = out.getvalue(), err.getvalue()
        return rc

    def init(self, authorize=True):
        path = self.root / "contract.json"
        path.write_text(json.dumps(self.contract))
        args = ["init", "--contract", str(path), "--state-root", str(self.root / "state")]
        if authorize:
            args += ["--authorize-implementation"]
        rc = self.call(*args)
        if rc == 0:
            self.task = Path(json.loads(self.last_out)["task_dir"])
        return rc

    def state(self):
        return json.loads((self.task / "state.json").read_text())

    def run_worker(self, scenario="ok", extra=(), expect=0):
        os.environ["MOCK_SCENARIO"] = scenario
        return self.call("run", "--task", str(self.task), "--opencode", str(self.binary), "--authorize-implementation", "--acknowledge-local-execution", "--experimental-cli-version", os.environ["MOCK_VERSION"], *extra, expect=expect)

    def check_command(self, code, output=None):
        self.contract["checks"] = [{"id": "C1", "argv": ["{python}", "-c", code], "criterion_ids": ["A1"], "output_contains": output or [], "trusted_inline": True}]

    def verify(self, expect=0):
        return self.call("verify", "--task", str(self.task), "--authorize-tests", expect=expect)

    def review_file(self, decision="accept"):
        s = self.state()
        r = {"task_id": "t1", "contract_sha256": s["contract_sha256"], "snapshot_sha256": s["checkpoint_sha256"], "verification_sha256": s["verification"]["sha256"],
             "decision": decision, "reviewer": "codex-test-coordinator", "criteria": [{"id": "A1", "result": "pass", "evidence": ["file:allowed.txt"], "note": "Read exact file and compared to acceptance."}], "rationale": "Test-only semantic review fixture."}
        path = self.root / "review.json"
        path.write_text(json.dumps(r))
        return path

    def test_init_detached_worktree_leaves_source_clean(self):
        self.assertEqual(self.init(), 0)
        self.assertEqual((self.repo / "allowed.txt").read_text(), "original\n")
        self.assertEqual(self.git("status", "--porcelain"), b"")
        self.assertTrue((self.task / "worktree/.git").is_file())

    def test_implementation_init_needs_authorization(self):
        self.assertEqual(self.init(False), 3)

    def test_dirty_source_rejected_without_stashing(self):
        (self.repo / "allowed.txt").write_text("user changes\n")
        self.assertEqual(self.init(), 3)
        self.assertEqual((self.repo / "allowed.txt").read_text(), "user changes\n")

    def test_duplicate_task_not_overwritten(self):
        self.assertEqual(self.init(), 0)
        self.assertEqual(self.init(), 3)

    def test_path_traversal_rejected(self):
        self.contract["allowed_paths"] = ["../escape"]
        self.assertNotEqual(self.init(), 0)

    def test_wildcards_rejected(self):
        self.contract["allowed_paths"] = ["*"]
        self.assertNotEqual(self.init(), 0)

    def test_protected_authorization_rejected(self):
        self.contract["allowed_paths"] = ["AGENTS.md"]
        self.assertNotEqual(self.init(), 0)

    def test_missing_acceptance_rejected(self):
        self.contract["acceptance"] = []
        self.assertNotEqual(self.init(), 0)

    def test_artifact_path_cannot_hide_source(self):
        self.contract["verification_artifacts"] = ["cache/"]
        (self.repo / "cache").mkdir()
        (self.repo / "cache/tracked.txt").write_text("tracked")
        self.git("add", "-f", "cache/tracked.txt")
        self.git("commit", "-qm", "tracked cache")
        self.assertNotEqual(self.init(), 0)

    def test_doctor_no_model_call(self):
        self.call("doctor", "--opencode", str(self.binary), expect=0)
        self.assertFalse((self.root / "calls.json").exists())

    def test_unknown_version_rejected(self):
        os.environ["MOCK_VERSION"] = "3.0.0"
        self.call("doctor", "--opencode", str(self.binary), expect=3)

    def test_missing_capability_rejected(self):
        os.environ["MOCK_SCENARIO"] = "no_capability"
        self.call("doctor", "--opencode", str(self.binary), expect=3)

    def test_run_requires_local_risk_acknowledgment(self):
        self.init()
        self.call("run", "--task", str(self.task), "--opencode", str(self.binary), "--authorize-implementation", expect=3)

    def test_run_requires_implementation_authorization(self):
        self.init()
        self.call("run", "--task", str(self.task), "--opencode", str(self.binary), "--acknowledge-local-execution", expect=3)

    def test_runtime_config_must_match(self):
        self.init();self.run_worker("bad_config", expect=3)
        self.assertFalse((self.root / "calls.json").exists())

    def test_runtime_formatter_must_be_disabled(self):
        self.init();self.run_worker("bad_formatter", expect=3)

    def test_config_startup_writes_detected(self):
        self.init();self.run_worker("config_writes", expect=3)

    def test_analyze_write_blocked(self):
        self.contract.update(mode="analyze", allowed_paths=[])
        self.init();self.run_worker("edit", expect=4)
        self.assertEqual(self.state()["status"], "POLICY_VIOLATION")

    def test_analyze_success_not_accepted(self):
        self.contract.update(mode="analyze", allowed_paths=[])
        self.init();self.run_worker()
        self.assertEqual(self.state()["status"], "AWAITING_VERIFY")

    def test_edit_and_incremental_resume(self):
        self.init();self.run_worker("edit")
        feedback = self.root / "feedback.txt";feedback.write_text("Change fixed to fixed-again; same scope.")
        self.run_worker("resume_edit", ("--feedback", str(feedback)))
        call = json.loads((self.root / "calls.json").read_text())
        self.assertIn("--session", call["args"])
        self.assertIn("ses_mock_123", call["args"])
        self.assertNotIn("--continue", call["args"])
        self.assertEqual((self.task / "worktree/allowed.txt").read_text(), "fixed-again\n")
        self.assertEqual((self.repo / "allowed.txt").read_text(), "original\n")

    def test_empty_resume_rejected(self):
        self.init();self.run_worker("edit");self.run_worker(expect=3)

    def test_fresh_session_requires_checkpoint(self):
        self.init();self.run_worker(extra=("--fresh-session",), expect=3)

    def test_fresh_session_with_checkpoint(self):
        self.init();self.run_worker("edit")
        checkpoint = self.root / "handoff.md";checkpoint.write_text("Verified file edit; tests not run. Preserve scope.")
        self.run_worker(extra=("--fresh-session", "--checkpoint", str(checkpoint)))
        call=json.loads((self.root / "calls.json").read_text())
        self.assertNotIn("--session", call["args"])

    def test_session_mismatch_rejected(self):
        self.init();self.run_worker()
        f=self.root / "feedback.txt";f.write_text("Check again")
        self.run_worker("wrong_session", ("--feedback", str(f)), expect=4)
        self.assertEqual(self.state()["status"], "PROTOCOL_ERROR")

    def test_unregistered_changes_rejected(self):
        self.init();self.run_worker("edit")
        (self.task / "worktree/other.txt").write_text("external edit")
        f=self.root / "feedback.txt";f.write_text("Check again")
        self.run_worker(extra=("--feedback", str(f)), expect=3)

    def test_attempt_limit(self):
        self.contract["max_attempts"]=1
        self.init();self.run_worker()
        f=self.root / "feedback.txt";f.write_text("Check again")
        self.run_worker(extra=("--feedback", str(f)), expect=3)

    def test_protected_file_violation(self):
        self.init();self.run_worker("protected", expect=4)
        self.assertEqual(self.state()["status"], "POLICY_VIOLATION")

    def test_untracked_file_violation(self):
        self.init();self.run_worker("new_file", expect=4)

    def test_ignored_file_violation(self):
        self.init();self.run_worker("ignored", expect=4)

    def test_out_of_scope_violation(self):
        self.init();self.run_worker("out_of_scope", expect=4)

    def test_symlink_violation(self):
        self.init();self.run_worker("symlink", expect=4)

    def test_staged_whitespace_violation(self):
        self.init();self.run_worker("stage", expect=4)
        self.assertTrue(any("Index changed" in x for x in self.state()["last_errors"]))

    def test_unstaged_whitespace_violation(self):
        self.init();self.run_worker("whitespace", expect=4)

    def test_commit_violation(self):
        self.init();self.run_worker("commit", expect=4)
        self.assertTrue(any("HEAD changed" in x for x in self.state()["last_errors"]))

    def test_rename_destination_checked(self):
        self.init();self.run_worker("rename", expect=4)

    def test_hardlink_violation(self):
        self.init();self.run_worker("hardlink", expect=4)

    def test_nonzero_exit_is_recorded(self):
        self.init();self.run_worker("nonzero", expect=4)
        meta=json.loads((self.task / "attempts/001/execution.json").read_text())
        self.assertEqual(meta["exit_code"], 7)
        self.assertEqual(self.state()["status"], "EXECUTION_FAILED")

    def test_invalid_ndjson(self):
        self.init();self.run_worker("bad_json", expect=4)
        self.assertEqual(self.state()["status"], "PROTOCOL_ERROR")

    def test_error_event_with_zero_exit(self):
        self.init();self.run_worker("error_event", expect=4)

    def test_missing_session(self):
        self.init();self.run_worker("no_session", expect=4)

    def test_ambiguous_session(self):
        self.init();self.run_worker("two_sessions", expect=4)

    def test_unstructured_success_not_accepted(self):
        self.init();self.run_worker("no_result", expect=4)

    def test_fake_test_claim_rejected(self):
        self.init();self.run_worker("fake_tests", expect=4)

    def test_blocked_result_not_success(self):
        self.init();self.run_worker("blocked", expect=4)
        self.assertEqual(self.state()["status"], "BLOCKED")

    def test_no_unrestricted_shell_no_auto(self):
        self.init();self.run_worker()
        record=json.loads((self.root / "calls.json").read_text())
        p=record["config"]["agent"][d.AGENT]["permission"]
        for name in ["bash","shell","task","subagent","external_directory"]:
            self.assertEqual(p[name], "deny")
        self.assertNotIn("--auto", record["args"])
        self.assertEqual(record["nested"], "1")

    def test_v2_candidate_policy_and_private_server(self):
        os.environ["MOCK_VERSION"]="2.0.0"
        self.init();self.run_worker()
        record=json.loads((self.root / "calls.json").read_text())
        self.assertIn("--standalone", record["args"])
        rules=record["config"]["agents"][d.AGENT]["permissions"]
        self.assertIn({"action":"shell","resource":"*","effect":"deny"},rules)

    def test_recursive_runner_rejected(self):
        with patch.dict(os.environ, {"OPENCODE_DELEGATE_ACTIVE":"1"}):
            self.call("doctor", "--opencode", str(self.binary), expect=3)

    def test_exclusive_lock(self):
        self.init()
        with (self.task / ".lock").open("w") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.run_worker(expect=3)

    def test_frozen_contract_tampering(self):
        self.init()
        c=json.loads((self.task / "contract.json").read_text());c["objective"]="changed"
        (self.task / "contract.json").write_text(json.dumps(c))
        self.run_worker(expect=2)

    def test_test_commands_require_authorization(self):
        self.check_command("print('checked')")
        self.init();self.run_worker()
        self.call("verify", "--task", str(self.task), expect=3)

    def test_real_checks_pass_and_review_gate(self):
        self.check_command("from pathlib import Path; assert Path('allowed.txt').read_text()=='fixed\\n'; print('checked')", ["checked"])
        self.init();self.run_worker("edit");self.verify()
        self.assertEqual(self.state()["status"], "REVIEW_REQUIRED")
        self.call("review", "--task", str(self.task), "--review", str(self.review_file()), expect=0)
        self.assertEqual(self.state()["status"], "ACCEPTED")

    def test_failed_independent_test_not_accepted(self):
        self.check_command("raise SystemExit(9)")
        self.init();self.run_worker("edit");self.verify(expect=5)
        self.assertEqual(self.state()["status"], "NEEDS_FIX")
        self.call("review", "--task", str(self.task), "--review", str(self.review_file()), expect=3)

    def test_output_requirement_detects_noop_test(self):
        self.check_command("pass", ["3 tests passed"])
        self.init();self.run_worker();self.verify(expect=5)

    def test_verifier_source_mutation_rejected(self):
        self.check_command("from pathlib import Path; Path('allowed.txt').write_text('changed by test')")
        self.init();self.run_worker();self.verify(expect=5)
        self.assertEqual(self.state()["status"], "VERIFICATION_MUTATED_SOURCE")

    def test_verification_artifacts_do_not_break_resume(self):
        self.contract["verification_artifacts"]=["cache/"]
        self.check_command("from pathlib import Path; Path('cache').mkdir(exist_ok=True); Path('cache/build.log').write_text('test artifact')")
        self.init();self.run_worker("edit");self.verify()
        f=self.root / "feedback.txt";f.write_text("One more scoped review")
        self.run_worker(extra=("--feedback",str(f)))

    def test_worker_cannot_write_verification_artifacts(self):
        self.contract["verification_artifacts"]=["cache/"]
        self.init();self.run_worker("ignored",expect=4)

    def test_stale_review_rejected(self):
        self.init();self.run_worker();self.verify()
        path=self.review_file();r=json.loads(path.read_text());r["snapshot_sha256"]="0"*64;path.write_text(json.dumps(r))
        self.call("review", "--task", str(self.task), "--review", str(path), expect=3)

    def test_tampered_verification_evidence_rejected(self):
        self.check_command("print('ok')")
        self.init();self.run_worker();self.verify()
        path=self.review_file()
        report=self.task / self.state()["verification"]["path"]
        (report.parent / "C1.out.log").write_text("tampered")
        self.call("review", "--task", str(self.task), "--review", str(path), expect=3)

    def test_review_requires_all_criteria(self):
        self.init();self.run_worker();self.verify()
        path=self.review_file();r=json.loads(path.read_text());r["criteria"]=[];path.write_text(json.dumps(r))
        self.call("review", "--task", str(self.task), "--review", str(path), expect=2)

    def test_post_verification_source_drift_rejected(self):
        self.init();self.run_worker();self.verify();path=self.review_file()
        (self.task / "worktree/allowed.txt").write_text("after verification")
        self.call("review", "--task", str(self.task), "--review", str(path), expect=3)

    def test_memory_requires_accepted_task(self):
        self.init();self.run_worker()
        path=self.root / "knowledge.json";path.write_text('{}')
        self.call("memory","--task",str(self.task),"--knowledge",str(path),expect=3)

    def test_memory_candidate_is_bound_not_auto_promoted(self):
        self.init();self.run_worker();self.verify()
        self.call("review","--task",str(self.task),"--review",str(self.review_file()),expect=0)
        path=self.root / "knowledge.json";path.write_text(json.dumps({"statement":"Verified test fixture fact", "applies_to":"this fixture only", "invalidated_by":"source changes", "evidence":["file:allowed.txt"]}))
        self.call("memory","--task",str(self.task),"--knowledge",str(path),expect=0)
        candidate=json.loads(Path(json.loads(self.last_out)["candidate"]).read_text())
        self.assertEqual(candidate["environment"],"local-test")
        self.assertIn("candidate",candidate["status"])

    def test_timeout_is_uncertain_not_retried(self):
        # A 1-second budget was flaky under parallel CI load even for the normal
        # recovery call. Keep the forced mock sleep (20s) above this real timeout.
        self.contract["timeout_seconds"]=5
        self.init();self.run_worker("timeout",expect=4)
        self.assertEqual(self.state()["status"],"OUTCOME_UNKNOWN")
        self.run_worker(expect=3)
        note=self.root / "recovery.txt";note.write_text("Inspected mock process/session; stopped, no background descendants.")
        self.call("recover","--task",str(self.task),"--confirmed-stopped","--note",str(note),expect=0)
        self.assertEqual(self.state()["status"],"RECOVERED")
        cp=self.root / "checkpoint.md";cp.write_text("Mock was stopped without changes; tests not run.")
        self.run_worker(extra=("--fresh-session","--checkpoint",str(cp)))

    def test_unknown_usage_not_estimated(self):
        self.init();self.run_worker()
        parsed=json.loads((self.task / "attempts/001/worker-result.json").read_text())
        self.assertIsNone(parsed["usage_observations"])
        self.assertIsNone(parsed["actual_model"])

    def test_observed_usage_preserved_without_estimating(self):
        self.init();self.run_worker("usage")
        parsed=json.loads((self.task / "attempts/001/worker-result.json").read_text())
        self.assertEqual(parsed["usage_observations"][0]["tokens"]["input"],123)

    def test_old_shell_interface_fails_loudly(self):
        p=subprocess.run(["bash",str(HERE / "delegate.sh"),"implement","/tmp","/tmp/task.txt"],capture_output=True)
        self.assertEqual(p.returncode,2)
        self.assertIn(b"V1 positional",p.stderr)

    def test_rule_order_changes_rejected(self):
        self.init();self.run_worker("reordered_permissions", expect=3)

    def test_rule_context_is_protected(self):
        self.contract["context"]=[{"path":"allowed.txt","purpose":"Frozen policy","kind":"rule"}]
        self.assertNotEqual(self.init(), 0)

    def test_reference_context_hash_updates_on_resume(self):
        self.contract["context"].append({"path":"allowed.txt","purpose":"Implementation target","kind":"reference"})
        self.init();self.run_worker("edit")
        f=self.root / "feedback.txt";f.write_text("Inspect the current contents")
        self.run_worker(extra=("--feedback",str(f)))
        packet=json.loads((self.task / "attempts/002/packet.json").read_text())
        item=next(x for x in packet["context_index"] if x["path"]=="allowed.txt")
        self.assertNotEqual(item["baseline_sha256"],item["current_sha256"])

    def test_path_prefix_boundary(self):
        self.assertTrue(d.matches("src/a.py",["src/"]))
        self.assertFalse(d.matches("src-other/a.py",["src/"]))

def run_one(name):
    import time
    started=time.monotonic()
    output=io.StringIO()
    suite=unittest.TestSuite([RunnerTests(name)])
    result=unittest.TextTestRunner(stream=output,verbosity=2).run(suite)
    return {"name":name,"passed":result.wasSuccessful(),"tests":result.testsRun,
            "elapsed_seconds":round(time.monotonic()-started,3),"log":output.getvalue()}

if __name__ == "__main__":
    if "--jobs" in sys.argv:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        jobs=int(sys.argv[sys.argv.index("--jobs")+1])
        names=unittest.defaultTestLoader.getTestCaseNames(RunnerTests)
        if "--start" in sys.argv:
            names=names[int(sys.argv[sys.argv.index("--start")+1]):]
        if "--count" in sys.argv:
            names=names[:int(sys.argv[sys.argv.index("--count")+1])]
        results=[]
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            for future in as_completed([pool.submit(run_one,n) for n in names]):
                r=future.result();results.append(r)
                print(("PASS " if r["passed"] else "FAIL ")+r["name"],flush=True)
                if not r["passed"]: print(r["log"],flush=True)
                if "--report" in sys.argv:
                    report=Path(sys.argv[sys.argv.index("--report")+1])
                    report.write_text(json.dumps({"tests":len(results),"passed":sum(x["passed"] for x in results),"complete":len(results)==len(names),"results":sorted(results,key=lambda x:x["name"])},indent=2))
        if "--report" in sys.argv:
            report=Path(sys.argv[sys.argv.index("--report")+1])
            report.write_text(json.dumps({"tests":len(results),"passed":sum(r["passed"] for r in results),"results":sorted(results,key=lambda x:x["name"])},indent=2))
        print(f"TOTAL {sum(r['passed'] for r in results)}/{len(results)} passed",flush=True)
        raise SystemExit(0 if all(r["passed"] for r in results) else 1)
    unittest.main(verbosity=2)
