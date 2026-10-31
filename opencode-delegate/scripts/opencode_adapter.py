"""Internal opencode adapter for opencode-delegate. Standard library only."""
from __future__ import annotations
import itertools
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
from typing import Any
from delegate_core import (GuardError, require, file_hash, digest, AGENT, PRELUDE, MAX_JSON, MAX_LOG, PROTECTED_NAMES, PROTECTED_PARTS, SECRET_NAMES)
from handoff import instruction_config_fingerprint


def probe(binary: str) -> dict:
    path = shutil.which(binary)
    require(path is not None, f"OpenCode executable not found: {binary}", 127)
    path = str(Path(path).resolve())
    def get(args):
        p = subprocess.run([path, *args], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=20)
        require(p.returncode == 0, f"OpenCode probe failed: {' '.join(args)}")
        return p.stdout.decode(errors="replace") + p.stderr.decode(errors="replace")
    version = get(["--version"]).strip()
    m = re.fullmatch(r"(?:opencode(?: version)?\s+)?v?(\d+)\.(\d+)\.(\d+)(?:[-+][A-Za-z0-9_.-]+)?", version, re.I)
    require(m is not None and int(m.group(1)) in (1, 2), "Unknown OpenCode version; no execution adapter is selected", 3)
    major = int(m.group(1))
    require(major != 1 or (int(m.group(2)), int(m.group(3))) >= (1, 1), "OpenCode 1.x requires >=1.1.1 permissions schema", 3)
    helptext = get(["run", "--help"])
    required = ["--format", "--agent", "--model", "--session"]
    if major == 2:
        required.append("--standalone")
    for flag in required:
        require(flag in helptext, f"OpenCode missing capability {flag}; stop rather than guess", 3)
    return {"binary": path, "binary_sha256": file_hash(Path(path)), "version": version,
            "major": major, "run_help_sha256": hashlib.sha256(helptext.encode()).hexdigest(),
            "supports_variant": "--variant" in helptext,
            "supports_standalone": "--standalone" in helptext,
            "adapter": f"opencode-v{major}-experimental", "certification": "unverified", "live_permissions_check_required": True}


def permission_config(c: dict, major: int, worktree: Path) -> tuple[dict, str, str]:
    deny_reads = [".env", ".env.*", "*/.env", "*/.env.*", "*.pem", "*.key", "*.p12", "*.pfx", ".git", ".git/*"]
    for name in sorted(SECRET_NAMES | {".ssh", ".aws"}):
        deny_reads.extend((name, "*/" + name, name + "/*", "*/" + name + "/*"))
    edit = {"*": "deny"}
    for p in c["allowed_paths"]:
        pattern = p + "*" if p.endswith("/") else p
        edit[pattern] = "allow"
        edit[str(worktree / pattern)] = "allow"
    for p in c["protected_paths"]:
        pattern = p + "*" if p.endswith("/") else p
        edit[pattern] = "deny"
        edit[str(worktree / pattern)] = "deny"
    for name in sorted(PROTECTED_NAMES | PROTECTED_PARTS | SECRET_NAMES):
        for pattern in (name, "*/" + name, name + "/*", "*/" + name + "/*"):
            edit[pattern] = "deny"
    # Reserve all case variants of AGENTS.* / CLAUDE.*; '*' is supported by
    # both candidate adapters. Avoid unsupported glob character classes.
    for stem in ("agents", "claude"):
        for chars in itertools.product(*[(ch.lower(), ch.upper()) for ch in stem]):
            name = "".join(chars) + ".*"
            for pattern in (name, "*/" + name):
                edit[pattern] = "deny"
    for pattern in deny_reads:
        edit[pattern] = "deny"
    reads = {"*": "allow", **{p: "deny" for p in deny_reads}}
    common = {"*": "deny", "read": reads, "glob": "allow", "grep": "deny", "edit": edit,
              "bash": "deny", "shell": "deny", "task": "deny", "subagent": "deny", "external_directory": "deny",
              "question": "deny", "skill": "deny", "webfetch": "deny", "websearch": "deny", "execute": "deny"}
    if major == 1:
        permission = common
        agent = {"mode": "primary", "description": "Bounded delegated worker; no shell or subagents", "prompt": PRELUDE, "model": c["model"], "permission": permission}
        return {"agent": {AGENT: agent}, "permission": permission, "formatter": False, "lsp": False, "autoupdate": False, "share": "disabled"}, "agent", "permission"
    rules = [{"action": "*", "resource": "*", "effect": "deny"}]
    for action in ("read", "glob", "grep", "edit"):
        value = common[action]
        for resource, effect in (value.items() if isinstance(value, dict) else [("*", value)]):
            rules.append({"action": action, "resource": resource, "effect": effect})
    for action in ("shell", "subagent", "external_directory", "question", "skill", "webfetch", "websearch", "execute"):
        rules.append({"action": action, "resource": "*", "effect": "deny"})
    agent = {"mode": "primary", "description": "Bounded delegated worker; no shell or subagents", "system": PRELUDE, "model": c["model"], "permissions": rules}
    return {"agents": {AGENT: agent}, "permissions": rules, "formatter": False}, "agents", "permissions"


def runtime_env(config: dict, worktree: Path) -> dict[str, str]:
    require(worktree.is_dir() and not worktree.is_symlink(), 'Missing/unsafe execution worktree', 3)
    env = {k: v for k, v in os.environ.items() if not k.startswith("OPENCODE_") and not k.startswith("GIT_")}
    # v2.2.3 run() prefers process.env.PWD over process.cwd(). Popen(cwd=...)
    # alone therefore leaves a caller's repository as the Session Location.
    env['PWD'] = str(worktree.resolve())
    env.update({"OPENCODE_CONFIG_CONTENT": json.dumps(config), "OPENCODE_PURE": "1",
                "OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
                "OPENCODE_DISABLE_LSP_DOWNLOAD": "1", "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
                "OPENCODE_DISABLE_CLAUDE_CODE": "1", "OPENCODE_DELEGATE_ACTIVE": "1",
                "PYTHONDONTWRITEBYTECODE": "1"})
    return env


def check_session_binding(info: dict, c: dict, session_id: str, wt: Path, env: dict) -> dict | None:
    """V2 explicit sessions override caller directory; inspect before and after run.

    This is a bounded metadata query, never a prompt/model request. V1 remains
    unverified and keeps its existing command surface.
    """
    if info['major'] != 2:
        return None
    require(isinstance(session_id, str) and re.fullmatch(r'ses_[A-Za-z0-9_-]+', session_id) is not None,
            'Invalid native session ID; no execution', 3)
    try:
        response = subprocess.run([info['binary'], 'api', 'GET', '/api/session/' + session_id, '--standalone'],
                                  cwd=str(wt), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise GuardError('Cannot inspect native session binding; no completed result accepted', 3) from exc
    require(response.returncode == 0 and len(response.stdout) <= MAX_JSON,
            'Cannot inspect native session binding; no completed result accepted', 3)
    from v2_config import decode_json
    try:
        payload = decode_json(response.stdout)
        require(isinstance(payload, dict) and isinstance(payload.get('data'), dict),
                'Unrecognized native session metadata', 3)
        value = payload['data']
        require(value.get('id') == session_id, 'Native session identity changed', 3)
        location = value.get('location')
        require(isinstance(location, dict) and isinstance(location.get('directory'), str),
                'Native session has no verifiable worktree location', 3)
        actual = Path(location['directory'])
        require(actual.is_absolute() and actual.is_dir() and not actual.is_symlink()
                and actual.resolve(strict=True) == wt.resolve(strict=True),
                'Native session moved outside the frozen worktree; preserve task and replan', 3)
        provider, model_id = c['model'].split('/', 1)
        model = value.get('model')
        require(isinstance(model, dict) and model.get('providerID') == provider and model.get('id') == model_id
                and model.get('variant') in (None, 'default'), 'Native session model changed', 3)
        require(value.get('agent') == AGENT, 'Native session agent changed', 3)
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise GuardError('Unrecognized native session metadata; no completed result accepted', 3) from exc
    return {'session_id': session_id, 'worktree': str(wt.resolve()), 'agent': AGENT,
            'model': {'providerID': provider, 'id': model_id, 'variant': model.get('variant')}}


def normalize_config(value: Any, ordered: bool = False) -> Any:
    if isinstance(value, dict):
        if ordered:
            return [[key, normalize_config(item, True)] for key, item in value.items()]
        return {key: normalize_config(item, key == "permission") for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_config(item, ordered) for item in value]
    return value


def check_effective_config(info: dict, config: dict, agent_key: str, perm_key: str, wt: Path, env: dict) -> str:
    # Never persist debug config: it may contain provider secrets.
    if agent_key == 'agents':
        from v2_config import decode_json, source_snapshot, resolved_agent
        def inspect(kind):
            result = subprocess.run([info['binary'], 'debug', kind, '--standalone'], cwd=str(wt), env=env,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
            require(result.returncode == 0, 'Cannot inspect private V2 ' + kind + '; no execution', 3)
            require(len(result.stdout) <= MAX_LOG, 'V2 inspection too large', 3)
            try:
                return decode_json(result.stdout)
            except (ValueError, UnicodeError) as e:
                raise GuardError('Unrecognized V2 inspection JSON; no execution', 3) from e
        before = source_snapshot(inspect('config'), config, wt)
        agent = resolved_agent(inspect('agents'), config)
        after = source_snapshot(inspect('config'), config, wt)
        require(before == after, 'V2 configuration changed during inspection; no execution', 3)
        return digest({'schema': 'v223-sources-agent-1', 'sources': before, 'agent': agent})
    p = subprocess.run([info["binary"], "debug", "config"], cwd=str(wt), env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=25)
    require(p.returncode == 0, "Cannot inspect effective OpenCode configuration; no execution", 3)
    require(len(p.stdout) <= MAX_LOG, "Effective config too large", 3)
    try:
        effective = json.loads(p.stdout)
    except (ValueError, UnicodeError) as e:
        raise GuardError("debug config is not recognized JSON; no execution", 3) from e
    expected = config[agent_key][AGENT]
    actual = effective.get(agent_key, {}).get(AGENT, {}) if isinstance(effective, dict) else {}
    require(isinstance(actual, dict) and all(actual.get(k) == v for k, v in expected.items()), "Effective custom-agent model/instructions/permissions do not match the frozen policy; no execution", 3)
    require(normalize_config(actual[perm_key], perm_key == "permission") == normalize_config(expected[perm_key], perm_key == "permission"), "Permission rule order changed; no execution", 3)
    require("tools" not in actual, "Unexpected legacy tool override in custom agent; no execution", 3)
    require(effective.get("formatter") is False, "Cannot confirm formatter is disabled", 3)
    # Some versions normalize permission objects or ignore inline config; fail closed.
    # Whitespace and unordered maps are irrelevant; ordered permission maps are not.
    return digest({"config": normalize_config(effective), "instruction_files": instruction_config_fingerprint(effective, wt)})


def parse_events(path: Path, task_id: str, expected_session: str | None) -> dict:
    require(path.stat().st_size <= MAX_LOG, "Event stream exceeds limit", 4)
    text_parts, session_ids, usage, errors = [], set(), [], []
    terminal = False
    part_ids = {}
    current_message = None
    seen_messages = set()
    identity_mode = None
    active_types = {"step_start", "text", "tool_use", "tool", "step_finish", "reasoning"}
    error_types = {"error", "session.error", "permission.denied"}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except ValueError as exc:
            raise GuardError("Malformed NDJSON event stream", 4) from exc
        require(isinstance(e, dict), "Non-object NDJSON event", 4)
        mids = set()
        for holder in (e, e.get("part", {}), e.get("properties", {})):
            if isinstance(holder, dict):
                sid = holder.get("sessionID", holder.get("session_id"))
                if sid is not None:
                    require(isinstance(sid, str) and re.fullmatch(r"ses_[A-Za-z0-9_-]+", sid) is not None, "Invalid session id", 4)
                    session_ids.add(sid)
                mid = holder.get("messageID", holder.get("message_id"))
                if mid is not None:
                    require(isinstance(mid, str) and bool(mid), "Invalid message id", 4)
                    mids.add(mid)
        require(len(mids) <= 1, "Conflicting message identities", 4)
        typ = e.get("type", "")
        require(typ in active_types | error_types, "Unknown transport event; adapter must be certified", 4)
        part = e.get("part", {})
        if typ in error_types:
            errors.append(e)
            terminal = False
            continue
        mid = next(iter(mids), None)
        identified = mid is not None
        if identity_mode is None:
            identity_mode = identified
        require(identity_mode == identified, "Mixed identified/unidentified message events", 4)
        if identified and mid != current_message:
            require(mid not in seen_messages, "Replayed/interleaved message", 4)
            seen_messages.add(mid)
            current_message = mid
            text_parts, part_ids, terminal = [], {}, False
        elif terminal and typ != "step_finish":
            # New activity cannot borrow an earlier stop; for legacy events
            # without IDs, discard the previous candidate as well.
            require(not identified, "Activity after final stop in the same message", 4)
            text_parts, part_ids, terminal = [], {}, False
        if typ != "step_finish":
            terminal = False
        if typ == "text":
            text = part.get("text") if isinstance(part, dict) else None
            text = text if text is not None else e.get("text")
            require(isinstance(text, str), "Unknown text event shape", 4)
            part_id = part.get("id") if isinstance(part, dict) else None
            if part_id is not None:
                require(isinstance(part_id, str) and bool(part_id), "Invalid text part id", 4)
            if part_id in part_ids:
                text_parts[part_ids[part_id]] = text
            else:
                if part_id is not None:
                    part_ids[part_id] = len(text_parts)
                text_parts.append(text)
        if typ == "step_finish":
            require(isinstance(part, dict), "Invalid finish event", 4)
            require(not terminal, "Duplicate finish after final stop", 4)
            terminal = part.get("reason") in ("stop", "end_turn")
            if "tokens" in part or "cost" in part:
                usage.append({k: part[k] for k in ("id", "tokens", "cost") if k in part})
    require(not errors, "OpenCode emitted error events even if process exit was zero", 4)
    require(len(session_ids) == 1, "Missing or ambiguous session id; do not infer 'latest session'", 4)
    sid = next(iter(session_ids))
    require(expected_session is None or sid == expected_session, "Returned session does not match this task", 4)
    require(terminal, "Missing final stop event; result is not transport-complete", 4)
    text = "".join(text_parts)
    matches_result = re.findall(r"BEGIN_DELEGATE_RESULT\s*(.*?)\s*END_DELEGATE_RESULT", text, re.S)
    require(len(matches_result) == 1, "Expected exactly one delimited structured result", 4)
    try:
        result = json.loads(matches_result[0])
    except ValueError as e:
        raise GuardError("Worker result is not valid JSON", 4) from e
    require(isinstance(result, dict) and set(result) == {"schema_version", "task_id", "status", "summary", "claims", "tests_run", "risks"}, "Invalid worker-result fields", 4)
    require(result["schema_version"] == 1, "Unsupported worker-result schema", 4)
    require(result["task_id"] == task_id and result["status"] in ("complete", "blocked"), "Worker result task/status mismatch", 4)
    require(isinstance(result["summary"], str) and isinstance(result["claims"], list) and isinstance(result["risks"], list), "Invalid result types", 4)
    for claim in result["claims"]:
        require(isinstance(claim, dict) and set(claim) == {"criterion_id", "claim", "evidence"}, "Invalid worker claim structure", 4)
        require(isinstance(claim["criterion_id"], str) and isinstance(claim["claim"], str) and isinstance(claim["evidence"], list) and all(isinstance(x, str) for x in claim["evidence"]), "Invalid worker claim types", 4)
    require(len({x["criterion_id"] for x in result["claims"]}) == len(result["claims"]), "Duplicate worker claims", 4)
    require(all(isinstance(x, str) for x in result["risks"]), "Worker risks must be strings", 4)
    require(result["tests_run"] == [], "Worker claims test execution despite shell denial; inspect before proceeding", 4)
    return {"session_id": sid, "final_message_id": current_message, "transport_identity": "message-bound" if identity_mode else "legacy-unidentified", "result": result, "usage_observations": usage or None,
            "actual_model": None, "usage_completeness": "partial" if usage else "unknown", "transport_terminal_observed": terminal, "usage_note": "Raw CLI observations only; no estimated tokens or billed cost. Requested model is recorded separately."}

