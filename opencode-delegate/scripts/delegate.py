#!/usr/bin/env python3
"""Bounded Codex -> OpenCode delegation. Python 3.9+, stdlib, Git, POSIX.

This is a local coordination/verification tool, NOT an OS security sandbox.
Only run trusted OpenCode installations and reviewed verification commands.
"""
from __future__ import annotations
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any
from delegate_core import (VERSION, STATE_SCHEMA_VERSION, SCAN_METRICS, AGENT, MAX_JSON, MAX_LOG, MAX_FILES, MAX_BYTES, PROTECTED_NAMES, PROTECTED_PARTS, SECRET_NAMES, BAD_STATES, PRELUDE, GuardError, require, now, canonical, digest, file_hash, read_json, read_text, atomic_json, clean_git_env, git)
from path_policy import safe_path, matches, paths_overlap, secret_path, assert_clean_visibility, protected, validate_contract
from state_store import locked, load, save
from lifecycle import begin as begin_operation, start_snapshot as operation_snapshot
from handoff import ambient_rule_paths, freeze_instructions, check_instructions, instruction_config_fingerprint, redact_excerpt, failure_packet
from opencode_adapter import probe, permission_config, runtime_env, normalize_config, check_effective_config, parse_events
from verification_support import verify_evidence, evidence_valid


def snapshot(root: Path) -> dict:
    """Hash all regular files, including ignored/untracked files; never follow symlinks."""
    require(root.is_dir() and not root.is_symlink(), "Worktree missing or symlinked")
    started = time.monotonic()
    entries: dict[str, Any] = {}
    size = 0
    stack = [root]
    while stack:
        directory = stack.pop()
        for entry in sorted(os.scandir(directory), key=lambda x: x.name):
            p = Path(entry.path)
            rel = p.relative_to(root).as_posix()
            if rel == ".git":
                continue
            info = entry.stat(follow_symlinks=False)
            if stat.S_ISLNK(info.st_mode):
                entries[rel] = {"kind": "symlink", "target": os.readlink(p)}
            elif stat.S_ISDIR(info.st_mode):
                stack.append(p)
            elif stat.S_ISREG(info.st_mode):
                require(info.st_nlink == 1, f"Hardlinked file not supported: {rel}")
                size += info.st_size
                require(size <= MAX_BYTES, f"Snapshot exceeds {MAX_BYTES} bytes at {rel} ({size} bytes scanned); narrow source checkout")
                entries[rel] = {"kind": "file", "sha256": file_hash(p), "mode": stat.S_IMODE(info.st_mode)}
            else:
                raise GuardError(f"Special filesystem object not supported: {rel}")
            require(len(entries) <= MAX_FILES, f"Snapshot exceeds {MAX_FILES} files at {rel}")
    marker = root / ".git"
    require(marker.is_file() and not marker.is_symlink(), "Expected managed linked worktree .git file")
    value = {"files": entries,
             "head": git(root, "rev-parse", "HEAD").stdout.decode().strip(),
             "index": hashlib.sha256(git(root, "ls-files", "--stage", "-z").stdout + git(root, "ls-files", "-v", "-z").stdout).hexdigest(),
             "git_marker": file_hash(marker)}
    value["sha256"] = digest(value)
    SCAN_METRICS.append({"files": len(entries), "bytes": size, "elapsed_seconds": round(time.monotonic() - started, 6)})
    return value


def differences(a: dict, b: dict) -> list[str]:
    return sorted(p for p in set(a["files"]) | set(b["files"]) if a["files"].get(p) != b["files"].get(p))


def invariant_errors(c: dict, baseline: dict, before: dict, after: dict, phase: str) -> list[str]:
    errors = []
    if after["head"] != baseline["head"]:
        errors.append("HEAD changed (commits/checkouts are forbidden)")
    if after["index"] != baseline["index"]:
        errors.append("Index changed (staging/index flags are forbidden)")
    if after["git_marker"] != baseline["git_marker"]:
        errors.append("Worktree Git identity changed")
    paths = differences(before, after) if phase == "verify" else sorted(set(differences(before, after)) | {p for p in differences(baseline, after) if not matches(p, c["verification_artifacts"])})
    for p in paths:
        is_artifact = phase == "verify" and matches(p, c["verification_artifacts"])
        if protected(p) or matches(p, c["protected_paths"]):
            errors.append(f"Protected path changed: {p}")
        elif after["files"].get(p, {}).get("kind") == "symlink":
            errors.append(f"Changed/new symlink: {p}")
        elif phase == "verify" and not is_artifact:
            errors.append(f"Verification modified source: {p}")
        elif phase != "verify" and (c["mode"] == "analyze" or not matches(p, c["allowed_paths"])):
            errors.append(f"Out-of-scope change: {p}")
    return errors


def current_checked(task: Path, s: dict, cp: dict) -> dict:
    current = snapshot(Path(s["worktree"]))
    require(current["sha256"] == cp["sha256"], "Unregistered worktree changes detected; do not overwrite/adopt them or silently retry", 3)
    return current


def group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def execute(argv: list[str], cwd: Path, env: dict[str, str], timeout: int, out: Path, err: Path, on_start=None) -> dict:
    """Bounded output, process-group termination, no shell, no auto retry."""
    start = time.monotonic()
    result = {"argv": argv, "started_at": now(), "exit_code": None, "reason": None, "pid": None}
    with out.open("wb") as stdout, err.open("wb") as stderr:
        try:
            p = subprocess.Popen(argv, cwd=str(cwd), env=env, stdin=subprocess.DEVNULL,
                                 stdout=stdout, stderr=stderr, start_new_session=True)
        except OSError as e:
            result.update(exit_code=127, reason="spawn_error", error=str(e))
            return result
        result["pid"] = p.pid
        try:
            if on_start:
                on_start(p.pid)
            while p.poll() is None:
                if time.monotonic() - start > timeout:
                    result["reason"] = "timeout"
                    break
                if out.stat().st_size + err.stat().st_size > MAX_LOG:
                    result["reason"] = "output_limit"
                    break
                time.sleep(0.05)
        except (KeyboardInterrupt, SystemExit):
            result["reason"] = "interrupted"
        finally:
            if result["reason"] is not None or p.poll() is None:
                try:
                    os.killpg(p.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    p.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
                if group_alive(p.pid):
                    try:
                        os.killpg(p.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
            p.wait()
        result["exit_code"] = p.returncode
        if group_alive(p.pid):
            result["reason"] = result["reason"] or "descendants_still_running"
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    if out.stat().st_size + err.stat().st_size > MAX_LOG:
        result["reason"] = result["reason"] or "output_limit"
    result["elapsed_seconds"] = round(time.monotonic() - start, 3)
    result["stdout_sha256"] = file_hash(out)
    result["stderr_sha256"] = file_hash(err)
    return result


def cmd_init(args) -> int:
    c = validate_contract(read_json(Path(args.contract).expanduser()))
    require(c["mode"] != "implement" or args.authorize_implementation, "Implementation requires explicit --authorize-implementation", 3)
    repo = Path(c["repo"]).resolve()
    require(repo.is_dir(), "Repository does not exist")
    top = Path(git(repo, "rev-parse", "--show-toplevel").stdout.decode().strip()).resolve()
    require(top == repo, "repo must identify the repository root, not a subdirectory")
    require(not git(repo, "status", "--porcelain", "--untracked-files=all").stdout, "Source worktree is dirty; no edits are copied, stashed, committed or deleted", 3)
    require(not any(x.startswith(b"160000 ") for x in git(repo, "ls-files", "--stage", "-z").stdout.split(b"\0")), "Submodules are not supported in this release", 3)
    c["repo"] = str(repo)
    state_root = Path(args.state_root).expanduser().resolve()
    require(state_root != repo and repo not in state_root.parents, "Task state must live outside the source repository")
    namespace = c["project_id"] + "-" + hashlib.sha256(str(repo).encode()).hexdigest()[:10]
    task = state_root / namespace / c["task_id"]
    require(not task.exists(), f"Task id already exists: {task}; never overwrite task state", 3)
    task.mkdir(parents=True, mode=0o700)
    base_commit = git(repo, "rev-parse", "HEAD").stdout.decode().strip()
    wt = task / "worktree"
    try:
        git(repo, "worktree", "add", "--detach", str(wt), base_commit)
        baseline = snapshot(wt)
        require(baseline["head"] == base_commit, "Unexpected checkout baseline")
        assert_clean_visibility(baseline)
        for source in c["verification_sources"]:
            require(any(matches(path, [source]) for path in baseline["files"]), "Verification source missing: " + source)
        instruction_manifest = freeze_instructions(c, repo, wt, baseline)
        for item in instruction_manifest:
            rel = item.get("worktree_path")
            if rel and rel not in c["protected_paths"]:
                c["protected_paths"].append(rel)
        # Rules discovered from the checkout must also participate in overlap checks.
        c = validate_contract(c)
        for prefix in c["verification_artifacts"]:
            require(not any(matches(p, [prefix]) for p in baseline["files"]), f"Artifact path masks baseline files: {prefix}")
        sources = []
        for item in c["context"]:
            p = wt / item["path"]
            require(p.is_file() and not p.is_symlink() and wt in p.resolve().parents, f"Context file missing/unsafe: {item['path']}")
            sources.append({**item, "sha256": file_hash(p)})
        atomic_json(task / "contract.json", c)
        atomic_json(task / "baseline.json", baseline)
        atomic_json(task / "instructions.json", instruction_manifest)
        s = {"state_schema_version": STATE_SCHEMA_VERSION, "runner_version": VERSION, "instruction_manifest_sha256": digest(instruction_manifest), "task_id": c["task_id"], "project_id": c["project_id"], "environment": c["environment"],
             "created_at": now(), "status": "READY", "worktree": str(wt), "base_commit": base_commit,
             "contract_sha256": digest(c), "base_sha256": baseline["sha256"], "checkpoint_sha256": baseline["sha256"],
             "context_sources": sources, "attempts": 0, "session_id": None, "last_attempt": None, "verification": None,
             "requested_model": c["model"], "requested_variant": c.get("variant"), "total_execution_seconds": 0.0}
        save(task, s, baseline)
    except Exception:
        # Preserve failed initialization for inspection; no destructive cleanup.
        atomic_json(task / "init-error.json", {"time": now(), "note": "Initialization failed; inspect task/worktree. No automatic removal performed."})
        raise
    print(json.dumps({"task_dir": str(task), "worktree": str(wt), "base_commit": base_commit, "status": "READY"}, indent=2))
    return 0


def cmd_run(args) -> int:
    task = Path(args.task).expanduser().resolve()
    with locked(task):
        c, s, base, cp = load(task)
        require(s["status"] not in BAD_STATES, f"Cannot run in state {s['status']}; inspect/recover instead", 3)
        require(args.acknowledge_local_execution, "Explicit --acknowledge-local-execution required; worktree is not an OS sandbox", 3)
        require(c["mode"] != "implement" or args.authorize_implementation, "Implementation requires --authorize-implementation", 3)
        require(s["attempts"] < c["max_attempts"], "Attempt budget exhausted; replan rather than auto-retry", 3)
        before = current_checked(task, s, cp)
        require(not s["attempts"] or args.feedback or args.fresh_session, "Resume requires focused --feedback, not an empty repeated task", 3)
        if s["status"] == "RECOVERED":
            require(args.fresh_session, "Recovered uncertain run requires fresh-session + coordinator checkpoint", 3)
        if args.fresh_session:
            require(args.checkpoint is not None, "Fresh session requires --checkpoint containing coordinator-reviewed facts/assumptions/evidence", 3)
        elif s["attempts"]:
            require(bool(s["session_id"]), "Previous session unknown; use an explicit fresh session with checkpoint", 3)
        feedback = read_text(Path(args.feedback)) if args.feedback else None
        checkpoint_text = read_text(Path(args.checkpoint)) if args.fresh_session else None
        info = probe(args.opencode)
        require(args.experimental_cli_version == info["version"], "No CLI version is certified yet. For a supervised trial only, explicitly pass --experimental-cli-version with the exact doctor version", 3)
        remaining = c.get("max_execution_seconds", 1800) - s["total_execution_seconds"]
        require(remaining >= 1, "Total execution time budget exhausted", 3)
        assert_clean_visibility(before)
        instructions = check_instructions(task, c, s)
        if s.get("runtime") and info != s["runtime"]:
            raise GuardError("OpenCode executable/version/capabilities changed during task; create a new task", 3)
        if c.get("variant"):
            require(info["supports_variant"], "Requested model variant is unsupported", 3)
        wt = Path(s["worktree"])
        config, agent_key, perm_key = permission_config(c, info["major"], wt)
        env = runtime_env(config)
        effective_hash = check_effective_config(info, config, agent_key, perm_key, wt, env)
        if s.get("effective_config_sha256"):
            require(s["effective_config_sha256"] == effective_hash, "Effective runtime config changed mid-task; rebaseline explicitly", 3)
        current_checked(task, s, cp)  # detect config/plugin initialization writes
        sid = None if args.fresh_session else s["session_id"]
        anchors = {k: c[k] for k in ("task_id", "project_id", "environment", "mode", "objective", "non_goals", "allowed_paths", "protected_paths", "acceptance")}
        context_index = []
        for item in s["context_sources"]:
            entry = before["files"].get(item["path"], {})
            context_index.append({**item, "baseline_sha256": item["sha256"], "current_sha256": entry.get("sha256"),
                                  "available": entry.get("kind") == "file"})
        packet = {"validation_plan": c["checks"], "verification_sources": c["verification_sources"], "instruction_manifest": instructions, "failure_packet": failure_packet(task, s, args.share_failure_details), "contract_sha256": s["contract_sha256"], "base_commit": s["base_commit"], "worktree_snapshot": before["sha256"],
                  "anchors": anchors, "context_index": context_index, "feedback": feedback, "checkpoint": checkpoint_text}
        prompt = PRELUDE + "\nTASK_PACKET:\n" + json.dumps(packet, ensure_ascii=True, indent=2)
        require(len(prompt.encode()) <= 49152, "Task packet exceeds 48 KiB; reduce handoff, not mandatory constraints")
        n = s["attempts"] + 1
        attempt = task / "attempts" / f"{n:03d}"
        s.pop("protocol_error", None)
        s.update(attempts=n, last_attempt=str(attempt.relative_to(task)), runtime=info,
                 effective_config_sha256=effective_hash, verification=None)
        begin_operation(task, s, before, "run", "PREPARING")
        attempt.mkdir(parents=True, mode=0o700)
        atomic_json(attempt / "operation.json", s["operation"])
        atomic_json(attempt / "packet.json", packet)
        atomic_json(attempt / "requested-policy.json", config)
        argv = [info["binary"], "run", "--format", "json", "--agent", AGENT, "--model", c["model"]]
        if info["major"] == 2:
            argv += ["--standalone"]
        if c.get("variant"):
            argv += ["--variant", c["variant"]]
        if sid:
            argv += ["--session", sid]
        argv += [prompt]
        s["status"] = "RUNNING"
        s["operation"]["stage"] = "starting"
        save(task, s)
        def started(pid):
            s["process_pid"] = pid
            s["operation"]["stage"] = "running"
            save(task, s)
        execution = execute(argv, wt, env, min(c["timeout_seconds"], max(1, int(remaining))), attempt / "events.ndjson", attempt / "stderr.log", started)
        # Store a prompt digest instead of duplicating the entire prompt in argv metadata.
        execution["argv"][-1] = "<task packet sha256:" + digest(packet) + ">"
        atomic_json(attempt / "execution.json", execution)
        s["total_execution_seconds"] += execution.get("elapsed_seconds", 0)
        try:
            after = snapshot(wt)
            errors = invariant_errors(c, base, before, after, "run")
            whitespace = git(wt, "diff", "--check", s["base_commit"], "--", check=False)
            if whitespace.returncode:
                errors.append("Tracked diff whitespace/check error: " + whitespace.stdout.decode(errors="replace")[:1000])
            atomic_json(attempt / "changes.json", {"delta": differences(before, after), "source_changes": [p for p in differences(base, after) if not matches(p, c["verification_artifacts"])], "errors": errors})
        except (GuardError, OSError) as e:
            after, errors = None, [f"Post-execution snapshot failed: {e}"]
        parsed = None
        try:
            if execution["exit_code"] == 0 and execution["reason"] is None:
                candidate = parse_events(attempt / "events.ndjson", c["task_id"], sid)
                require(all(x["criterion_id"] in {a["id"] for a in c["acceptance"]} for x in candidate["result"]["claims"]), "Worker referenced unknown acceptance criterion", 4)
                atomic_json(attempt / "worker-result.json", candidate)
                parsed = candidate  # Commit success ONLY after validation and persistence.
        except (GuardError, UnicodeError, OSError) as e:
            s["protocol_error"] = str(e)
        if execution["reason"] in ("timeout", "interrupted", "output_limit", "descendants_still_running"):
            s["status"] = "OUTCOME_UNKNOWN"
        elif errors:
            s["status"] = "POLICY_VIOLATION"
        elif execution["exit_code"] != 0:
            s["status"] = "EXECUTION_FAILED"
        elif parsed is None:
            s["status"] = "PROTOCOL_ERROR"
        else:
            s["session_id"] = parsed["session_id"]
            s["status"] = "AWAITING_VERIFY" if parsed["result"]["status"] == "complete" else "BLOCKED"
        s["last_errors"] = errors
        s["operation"].update(stage="uncertain" if s["status"] == "OUTCOME_UNKNOWN" else "finished", errors=errors)
        save(task, s, after if s["status"] != "OUTCOME_UNKNOWN" else None)
        print(json.dumps({"status": s["status"], "task_dir": str(task), "attempt": n,
                          "session_id": s["session_id"], "execution_exit_code": execution["exit_code"],
                          "next": "Run independent verify; no acceptance yet" if s["status"] == "AWAITING_VERIFY" else "Inspect state and evidence before any follow-up"}, indent=2))
        return 0 if s["status"] == "AWAITING_VERIFY" else 4


def cmd_verify(args) -> int:
    task = Path(args.task).expanduser().resolve()
    with locked(task):
        c, s, base, cp = load(task)
        require(s["status"] in ("AWAITING_VERIFY", "NEEDS_FIX", "REVIEW_REQUIRED", "EVIDENCE_ERROR"), f"Cannot verify in state {s['status']}", 3)
        require(not c["checks"] or args.authorize_tests, "Review test commands/code first, then pass --authorize-tests", 3)
        check_instructions(task, c, s)
        before = current_checked(task, s, cp)
        initial = invariant_errors(c, base, before, before, "run")
        require(not initial, "; ".join(initial), 3)
        wt = Path(s["worktree"])
        stamp = str(time.time_ns())
        evidence = task / "verification" / stamp
        s["verification"] = None
        begin_operation(task, s, before, "verify", "VERIFYING")
        evidence.mkdir(parents=True, mode=0o700)
        verification_start = time.monotonic()
        results, errors = [], []
        evidence_errors = []
        previous = before
        uncertain = False
        for check in c["checks"]:
            cwd = (wt / check["cwd"]).resolve()
            require(cwd == wt or wt in cwd.parents, "Test cwd escapes worktree")
            argv = [x.replace("{python}", sys.executable).replace("{worktree}", str(wt)).replace("{evidence_dir}", str(evidence)) for x in check["argv"]]
            out, err = evidence / (check["id"] + ".out.log"), evidence / (check["id"] + ".err.log")
            env = clean_git_env()
            env.update(PYTHONDONTWRITEBYTECODE="1", OPENCODE_DELEGATE_ACTIVE="1")
            # Record the specific test BEFORE spawn; stale PIDs from a previous
            # check must not be interpreted as the current process identity.
            s["process_pid"] = None
            s["operation"].update(stage="starting", check_id=check["id"])
            save(task, s)
            def started(pid):
                s["process_pid"] = pid
                s["operation"]["stage"] = "running"
                save(task, s)
            result = execute(argv, cwd, env, check["timeout_seconds"], out, err, started)
            content = (out.read_bytes()[:MAX_LOG] + err.read_bytes()[:MAX_LOG]).decode(errors="replace")
            result.update(id=check["id"], criterion_ids=check["criterion_ids"], output_requirements_met=all(x in content for x in check["output_contains"]))
            result["passed"] = result["exit_code"] == 0 and result["reason"] is None and result["output_requirements_met"]
            results.append(result)
            try:
                after = snapshot(wt)
                errors += invariant_errors(c, base, previous, after, "verify")
                previous = after
            except (GuardError, OSError) as e:
                errors.append(str(e))
            if result["reason"] in ("timeout", "interrupted", "output_limit", "descendants_still_running"):
                uncertain = True
            s["operation"].update(errors=list(errors), stage="uncertain" if uncertain else "checking")
            save(task, s)  # Never lose already observed source-mutation evidence.
            if errors or uncertain:
                break
        after = previous
        diff_result = {"exit_code": None, "complete": False}
        try:
            tracked = git(wt, "diff", "--binary", "--no-ext-diff", "--no-textconv", s["base_commit"], "--", check=False)
            diff_result["exit_code"] = tracked.returncode
            (evidence / "diff.stderr.log").write_bytes(tracked.stderr)
            if tracked.returncode:
                evidence_errors.append("git diff failed; see diff.stderr.log")
            else:
                (evidence / "tracked.patch").write_bytes(tracked.stdout)
                diff_result["complete"] = True
        except (OSError, GuardError) as exc:
            evidence_errors.append("Diff evidence generation failed: " + str(exc))
        files = {p: after["files"].get(p) for p in differences(base, after) if not matches(p, c["verification_artifacts"])}
        atomic_json(evidence / "source-changes.json", files)
        report = {"task_id": c["task_id"], "time": now(), "contract_sha256": s["contract_sha256"], "snapshot_sha256": after["sha256"],
                  "checks": results, "errors": errors + evidence_errors, "diff_result": diff_result, "all_checks_passed": len(results) == len(c["checks"]) and all(r["passed"] for r in results) and not errors and not evidence_errors and not uncertain,
                  "evidence_hashes": {p.name: file_hash(p) for p in evidence.iterdir() if p.is_file()}}
        atomic_json(evidence / "verification.json", report)
        s["verification"] = {"path": str((evidence / "verification.json").relative_to(task)), "sha256": file_hash(evidence / "verification.json")}
        s["status"] = "OUTCOME_UNKNOWN" if uncertain else "VERIFICATION_MUTATED_SOURCE" if errors else "EVIDENCE_ERROR" if evidence_errors else "REVIEW_REQUIRED" if report["all_checks_passed"] else "NEEDS_FIX"
        s["total_verification_seconds"] = round(s.get("total_verification_seconds", 0) + time.monotonic() - verification_start, 3)
        s["operation"].update(stage="uncertain" if uncertain else "finished", errors=errors)
        save(task, s, after if not uncertain else None)
        print(json.dumps({"status": s["status"], "verification": s["verification"], "note": "Passing commands are not semantic acceptance. Codex must review every criterion."}, indent=2))
        return 0 if s["status"] == "REVIEW_REQUIRED" else 5


def cmd_review(args) -> int:
    task = Path(args.task).expanduser().resolve()
    with locked(task):
        c, s, base, cp = load(task)
        require(s["status"] in ("REVIEW_REQUIRED", "NEEDS_FIX"), "Review requires completed independent verification", 3)
        check_instructions(task, c, s)
        current = current_checked(task, s, cp)
        v = verify_evidence(task, s)
        r = read_json(Path(args.review))
        fields = {"task_id", "contract_sha256", "snapshot_sha256", "verification_sha256", "decision", "reviewer", "criteria", "rationale"}
        require(isinstance(r, dict) and set(r) == fields, "Invalid review fields")
        require(r["task_id"] == c["task_id"] and r["contract_sha256"] == s["contract_sha256"] and r["snapshot_sha256"] == current["sha256"] and r["verification_sha256"] == s["verification"]["sha256"], "Stale/wrong review binding", 3)
        require(isinstance(r["reviewer"], str) and bool(r["reviewer"].strip()) and isinstance(r["rationale"], str) and bool(r["rationale"].strip()), "Reviewer/rationale required")
        require(r["decision"] in ("accept", "needs_fix", "reject"), "Invalid review decision")
        require(isinstance(r["criteria"], list), "Review criteria must be a list")
        ids = []
        for item in r["criteria"]:
            require(isinstance(item, dict) and set(item) == {"id", "result", "evidence", "note"}, "Invalid review criterion")
            require(item["result"] in ("pass", "fail", "blocked"), "Invalid criterion result")
            require(isinstance(item["evidence"], list) and item["evidence"] and all(isinstance(x, str) and evidence_valid(x, v, Path(s["worktree"]), item["id"], item["result"] == "pass") for x in item["evidence"]), "Each criterion requires existing file/test/diff evidence")
            require(isinstance(item["note"], str) and bool(item["note"].strip()), "Criterion needs a semantic review note")
            ids.append(item["id"])
        require(len(ids) == len(set(ids)) and set(ids) == {x["id"] for x in c["acceptance"]}, "Review must cover every acceptance criterion exactly once")
        if r["decision"] == "accept":
            require(v["all_checks_passed"] and all(x["result"] == "pass" for x in r["criteria"]), "Cannot accept failed checks/criteria", 3)
            require(v["snapshot_sha256"] == current["sha256"], "Verification is stale", 3)
        path = task / "reviews" / (str(time.time_ns()) + ".json")
        atomic_json(path, {**r, "reviewed_at": now(), "instruction_manifest_sha256": s["instruction_manifest_sha256"], "note": "Coordinator declaration; not cryptographic reviewer authentication."})
        s["status"] = {"accept": "ACCEPTED", "needs_fix": "NEEDS_FIX", "reject": "REJECTED"}[r["decision"]]
        s["review"] = {"path": str(path.relative_to(task)), "sha256": file_hash(path)}
        save(task, s)
        print(json.dumps({"status": s["status"], "review": s["review"], "source_worktree_automatically_merged": False}, indent=2))
        return 0


def cmd_recover(args) -> int:
    task = Path(args.task).expanduser().resolve()
    with locked(task):
        c, s, base, cp = load(task)
        require(s["status"] in ("PREPARING", "RUNNING", "VERIFYING", "OUTCOME_UNKNOWN"), "Only interrupted/uncertain tasks can be recovered; CLEANING uses cleanup --confirm", 3)
        require(args.confirmed_stopped, "Inspect CLI/server/session/descendants before --confirmed-stopped", 3)
        note = read_text(Path(args.note))
        start = operation_snapshot(task, s)
        phase = s["operation"]["phase"]
        require(phase in ("run", "verify"), "Wrong recovery phase", 3)
        pid = s.get("process_pid")
        require(not pid or not group_alive(pid), "Recorded process group is still present; do not signal potentially reused PIDs blindly", 3)
        current = snapshot(Path(s["worktree"]))
        errors = list(s["operation"].get("errors", []))
        errors += invariant_errors(c, base, start, current, phase)
        if s["status"] == "PREPARING" and current["sha256"] != start["sha256"]:
            errors.append("Worktree changed before executor launch")
        errors = sorted(set(errors))
        atomic_json(task / "recovery" / (str(time.time_ns()) + ".json"), {"time": now(), "note": note,
                    "old_status": s["status"], "operation": s["operation"], "changes": differences(start, current),
                    "errors": errors, "snapshot": current["sha256"]})
        s["status"] = ("VERIFICATION_MUTATED_SOURCE" if phase == "verify" else "POLICY_VIOLATION") if errors else "RECOVERED"
        s["operation"].update(stage="reconciled", errors=errors)
        s["session_id"] = None
        s["verification"] = None
        save(task, s, current)
        print(json.dumps({"status": s["status"], "phase": phase, "next": "Fresh session with reviewed checkpoint required; previous result is not accepted."}))
        return 3 if errors else 0


def cmd_memory(args) -> int:
    task = Path(args.task).expanduser().resolve()
    with locked(task):
        c, s, base, cp = load(task)
        require(s["status"] == "ACCEPTED", "Only accepted tasks can propose verified knowledge", 3)
        check_instructions(task, c, s)
        current_checked(task, s, cp)
        v = verify_evidence(task, s)
        require(file_hash(task / s["review"]["path"]) == s["review"]["sha256"], "Review evidence changed", 3)
        k = read_json(Path(args.knowledge))
        require(isinstance(k, dict) and set(k) == {"statement", "applies_to", "invalidated_by", "evidence"}, "Knowledge requires statement/applies_to/invalidated_by/evidence")
        for name in ("statement", "applies_to", "invalidated_by"):
            require(isinstance(k[name], str) and bool(k[name].strip()), f"Knowledge {name} required")
        require(isinstance(k["evidence"], list) and k["evidence"] and all(isinstance(x, str) and evidence_valid(x, v, Path(s["worktree"])) for x in k["evidence"]), "Knowledge needs verified evidence")
        path = task / "knowledge-candidates" / (str(time.time_ns()) + ".json")
        atomic_json(path, {**k, "status": "candidate_for_coordinator_promotion", "instruction_manifest_sha256": s["instruction_manifest_sha256"], "verified_at": now(), "project_id": c["project_id"], "environment": c["environment"], "task_id": c["task_id"], "base_commit": s["base_commit"], "snapshot_sha256": cp["sha256"], "review": s["review"]})
        print(json.dumps({"candidate": str(path), "shared_project_memory_modified": False}))
        return 0


def cmd_status(args) -> int:
    task = Path(args.task).expanduser().resolve()
    # One atomic state.json + immutable referenced checkpoint is a consistent
    # committed generation, even while a writer holds the task lock.
    c, s, base, cp = load(task, allow_legacy=True)
    value = {k: v for k, v in s.items() if k != "context_sources"}
    value.update(task_dir=str(task), worktree_matches_checkpoint=None,
                 legacy_read_only=s.get("state_schema_version", 1) == 1,
                 observation="last committed generation; not live process state",
                 coordinator_usage={"tokens": None, "cost": None, "completeness": "unknown"})
    if args.check_worktree:
        try:
            with locked(task):
                c, fresh, base, cp = load(task, allow_legacy=True)
                if fresh.get("generation") != s.get("generation"):
                    value["scan_skipped"] = "state changed; query again"
                elif fresh["status"] in ("PREPARING", "RUNNING", "VERIFYING", "OUTCOME_UNKNOWN", "CLEANING", "ARCHIVED"):
                    value["scan_skipped"] = "operation not quiescent or worktree archived"
                else:
                    value["worktree_matches_checkpoint"] = snapshot(Path(s["worktree"]))["sha256"] == cp["sha256"]
                    value["status_scan"] = SCAN_METRICS[-1] if SCAN_METRICS else None
        except GuardError as exc:
            if "Task is locked" not in str(exc):
                raise
            value["scan_skipped"] = "writer active; displaying committed state only"
    print(json.dumps(value, indent=2))
    return 0


def cmd_export(args) -> int:
    """Export tracked AND untracked changes without committing or applying them."""
    import zipfile
    task = Path(args.task).expanduser().resolve()
    output = Path(args.output).expanduser().absolute()
    with locked(task):
        c, s, base, cp = load(task)
        require(s["status"] in ("ACCEPTED", "REJECTED"), "Export requires a reviewed terminal task", 3)
        check_instructions(task, c, s)
        current = current_checked(task, s, cp)
        verify_evidence(task, s)
        require(file_hash(task / s["review"]["path"]) == s["review"]["sha256"], "Review changed", 3)
        require(not output.exists() and not output.is_symlink(), "Export destination already exists", 3)
        require(task not in output.resolve().parents and Path(c["repo"]) not in output.resolve().parents, "Export must be outside task/source repository", 3)
        output.parent.mkdir(parents=True, exist_ok=True)
        changed = [p for p in differences(base, current) if not matches(p, c["verification_artifacts"])]
        manifest = {"schema_version": 1, "task_id": c["task_id"], "base_commit": s["base_commit"], "base_sha256": s["base_sha256"],
                    "snapshot_sha256": cp["sha256"], "contract_sha256": s["contract_sha256"], "instruction_manifest_sha256": s["instruction_manifest_sha256"], "status": s["status"], "files": {}}
        fd, temporary = tempfile.mkstemp(prefix=".delegate-export-", dir=str(output.parent))
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w+b") as target:
                with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as bundle:
                    for rel in changed:
                        safe_path(rel)
                        item = current["files"].get(rel)
                        manifest["files"][rel] = {"before": base["files"].get(rel), "after": item}
                        if item is not None:
                            require(item["kind"] == "file", "Export refuses non-regular payload")
                            path = Path(s["worktree"]) / rel
                            require(file_hash(path) == item["sha256"], "Payload changed during export", 3)
                            bundle.write(path, "files/" + rel)
                    bundle.writestr("manifest.json", json.dumps(manifest, indent=2))
                    report = task / s["verification"]["path"]
                    bundle.write(report, "verification.json")
                    bundle.write(report.parent / "tracked.patch", "tracked.patch")
                target.flush(); os.fsync(target.fileno())
            current_checked(task, s, cp)
            os.link(temporary, output)  # Atomic create; never replace a concurrent user's file.
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        s["delivery"] = {"path": str(output), "sha256": file_hash(output), "snapshot_sha256": cp["sha256"], "created_at": now()}
        save(task, s)
        print(json.dumps({"delivery": s["delivery"], "files": len(changed), "auto_applied": False}, indent=2))
    return 0


def cmd_cleanup(args) -> int:
    task = Path(args.task).expanduser().resolve()
    with locked(task):
        c, s, base, cp = load(task)
        require(s["status"] in ("ACCEPTED", "REJECTED", "CLEANING", "ARCHIVED"), "Only reviewed terminal tasks can be cleaned; uncertain tasks must be preserved", 3)
        verify_evidence(task, s)
        require(file_hash(task / s["review"]["path"]) == s["review"]["sha256"], "Review changed", 3)
        delivery = s.get("delivery")
        require(delivery and delivery["snapshot_sha256"] == cp["sha256"], "Export this exact snapshot before cleanup", 3)
        require(Path(delivery["path"]).is_file() and file_hash(Path(delivery["path"])) == delivery["sha256"], "Delivery archive missing or changed", 3)
        wt = Path(s["worktree"])
        if s["status"] in ("CLEANING", "ARCHIVED"):
            start = operation_snapshot(task, s)
            require(s["operation"]["phase"] == "cleanup" and start["sha256"] == cp["sha256"], "Invalid cleanup intent", 3)
            require(s["operation"].get("delivery") == delivery, "Cleanup delivery binding changed", 3)
        if s["status"] == "ARCHIVED":
            require(not wt.exists() and not wt.is_symlink(), "Archived path reappeared; never delete it", 3)
            print(json.dumps({"status": "ARCHIVED", "already_cleaned": True}))
            return 0
        require(not s.get("process_pid") or not group_alive(s["process_pid"]), "Process group still present; cleanup denied", 3)
        exists = wt.exists() or wt.is_symlink()
        if exists:
            current_checked(task, s, cp)
            check_instructions(task, c, s)
        else:
            require(s["status"] == "CLEANING", "Worktree absent without durable cleanup intent", 3)
            # A partial removal that left Git registration is not silently adopted.
            registered = git(Path(c["repo"]), "worktree", "list", "--porcelain", "-z").stdout.decode()
            require(not any(line == "worktree " + str(wt) for line in registered.split("\0")),
                    "Worktree absent but Git registration remains; inspect before completing cleanup", 3)
        plan = {"remove_worktree": str(wt), "preserve_evidence": str(task), "export": delivery, "dry_run": not args.confirm}
        if args.confirm:
            if s["status"] != "CLEANING":
                begin_operation(task, s, cp, "cleanup", "CLEANING", {"delivery": dict(delivery)})
            if exists:
                git(Path(c["repo"]), "worktree", "remove", "--force", str(wt))
            s["status"] = "ARCHIVED"
            s["operation"]["stage"] = "finished"
            save(task, s)
        print(json.dumps(plan, indent=2))
    return 0


def cmd_failure(args) -> int:
    task = Path(args.task).expanduser().resolve()
    with locked(task):
        _, s, _, _ = load(task)
        print(json.dumps(failure_packet(task, s, args.include_details), indent=2))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="command", required=True)
    d = sub.add_parser("doctor", help="Probe CLI capabilities, no model call")
    d.add_argument("--opencode", default="opencode")
    d.set_defaults(func=lambda a: (print(json.dumps(probe(a.opencode), indent=2)) or 0))
    d = sub.add_parser("init", help="Freeze contract and create a detached worktree")
    d.add_argument("--contract", required=True)
    d.add_argument("--state-root", default=str(Path.home() / ".local/state/opencode-delegate"))
    d.add_argument("--authorize-implementation", action="store_true")
    d.set_defaults(func=cmd_init)
    d = sub.add_parser("run", help="Execute one attempt; never auto-accept")
    d.add_argument("--task", required=True)
    d.add_argument("--opencode", default="opencode")
    d.add_argument("--authorize-implementation", action="store_true")
    d.add_argument("--acknowledge-local-execution", action="store_true")
    d.add_argument("--experimental-cli-version", help="Exact doctor version; explicit supervised trial, not certification")
    d.add_argument("--share-failure-details", action="store_true", help="Share reviewed/redacted failure excerpts, not just metadata")
    d.add_argument("--feedback")
    d.add_argument("--fresh-session", action="store_true")
    d.add_argument("--checkpoint")
    d.set_defaults(func=cmd_run)
    d = sub.add_parser("verify", help="Run frozen checks and record independent evidence")
    d.add_argument("--task", required=True)
    d.add_argument("--authorize-tests", action="store_true")
    d.set_defaults(func=cmd_verify)
    d = sub.add_parser("review", help="Bind Codex's semantic verdict to exact evidence")
    d.add_argument("--task", required=True)
    d.add_argument("--review", required=True)
    d.set_defaults(func=cmd_review)
    d = sub.add_parser("recover", help="Record manual reconciliation, never auto retry")
    d.add_argument("--task", required=True)
    d.add_argument("--confirmed-stopped", action="store_true")
    d.add_argument("--note", required=True)
    d.set_defaults(func=cmd_recover)
    d = sub.add_parser("memory", help="Emit an evidence-bound knowledge candidate")
    d.add_argument("--task", required=True)
    d.add_argument("--knowledge", required=True)
    d.set_defaults(func=cmd_memory)
    d = sub.add_parser("status", help="Inspect state and snapshot drift")
    d.add_argument("--task", required=True)
    d.add_argument("--check-worktree", action="store_true")
    d.set_defaults(func=cmd_status)
    d = sub.add_parser("failure", help="Preview failure metadata or redacted excerpts; does not call a model")
    d.add_argument("--task", required=True)
    d.add_argument("--include-details", action="store_true")
    d.set_defaults(func=cmd_failure)
    d = sub.add_parser("export", help="Export exact reviewed changes, including new files and deletions")
    d.add_argument("--task", required=True)
    d.add_argument("--output", required=True)
    d.set_defaults(func=cmd_export)
    d = sub.add_parser("cleanup", help="Preview terminal worktree removal; requires intact export; preserves evidence")
    d.add_argument("--task", required=True)
    d.add_argument("--confirm", action="store_true")
    d.set_defaults(func=cmd_cleanup)
    return p


def main(argv=None) -> int:
    os.umask(0o077)
    SCAN_METRICS.clear()
    try:
        require(os.name == "posix", "This release supports macOS/Linux only")
        require(not os.environ.get("OPENCODE_DELEGATE_ACTIVE"), "Recursive delegation is forbidden", 3)
        a = parser().parse_args(argv)
        return a.func(a)
    except GuardError as e:
        print(json.dumps({"error": str(e), "exit_code": e.code}), file=sys.stderr)
        return e.code
    except (OSError, UnicodeError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError) as e:
        print(json.dumps({"error": f"Stopped safely: {type(e).__name__}: {e}", "note": "Inspect task state; no automatic cleanup/retry was performed."}), file=sys.stderr)
        return 2

if __name__ == "__main__":
    sys.exit(main())
