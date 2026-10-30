"""Internal opencode adapter for opencode-delegate. Standard library only."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
from typing import Any
from delegate_core import (GuardError, require, file_hash, digest, AGENT, PRELUDE, MAX_LOG, PROTECTED_NAMES, PROTECTED_PARTS, SECRET_NAMES)
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


def runtime_env(config: dict) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("OPENCODE_") and not k.startswith("GIT_")}
    env.update({"OPENCODE_CONFIG_CONTENT": json.dumps(config), "OPENCODE_PURE": "1",
                "OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_DISABLE_DEFAULT_PLUGINS": "1",
                "OPENCODE_DISABLE_LSP_DOWNLOAD": "1", "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1",
                "OPENCODE_DISABLE_CLAUDE_CODE": "1", "OPENCODE_DELEGATE_ACTIVE": "1",
                "PYTHONDONTWRITEBYTECODE": "1"})
    return env


def normalize_config(value: Any, ordered: bool = False) -> Any:
    if isinstance(value, dict):
        if ordered:
            return [[key, normalize_config(item, True)] for key, item in value.items()]
        return {key: normalize_config(item, key in ("permission", "permissions")) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_config(item, ordered) for item in value]
    return value


def check_effective_config(info: dict, config: dict, agent_key: str, perm_key: str, wt: Path, env: dict) -> str:
    # Never persist debug config: it may contain provider secrets.
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
    require(json.dumps(actual[perm_key], ensure_ascii=True, separators=(",", ":")) == json.dumps(expected[perm_key], ensure_ascii=True, separators=(",", ":")), "Permission rule order changed; no execution", 3)
    require("tools" not in actual, "Unexpected legacy tool override in custom agent; no execution", 3)
    require(effective.get("formatter") is False, "Cannot confirm formatter is disabled", 3)
    # Some versions normalize permission objects or ignore inline config; fail closed.
    # Whitespace and unordered maps are irrelevant; ordered permission maps are not.
    return digest({"config": normalize_config(effective), "instruction_files": instruction_config_fingerprint(effective, wt)})


def parse_events(path: Path, task_id: str, expected_session: str | None) -> dict:
    text_parts, session_ids, usage, errors = [], set(), [], []
    terminal = False
    part_ids = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            e = json.loads(line)
        except ValueError as exc:
            raise GuardError("Malformed NDJSON event stream", 4) from exc
        require(isinstance(e, dict), "Non-object NDJSON event", 4)
        for holder in (e, e.get("part", {}), e.get("properties", {})):
            if isinstance(holder, dict):
                sid = holder.get("sessionID", holder.get("session_id"))
                if sid is not None:
                    require(isinstance(sid, str) and re.fullmatch(r"ses_[A-Za-z0-9_-]+", sid) is not None, "Invalid session id", 4)
                    session_ids.add(sid)
        typ = e.get("type", "")
        part = e.get("part", {})
        if typ in ("step_start", "tool_use", "tool"):
            terminal = False
        if typ == "text":
            text = part.get("text") if isinstance(part, dict) else None
            text = text if text is not None else e.get("text")
            require(isinstance(text, str), "Unknown text event shape", 4)
            part_id = part.get("id") if isinstance(part, dict) else None
            if part_id in part_ids:
                text_parts[part_ids[part_id]] = text
            else:
                if isinstance(part_id, str):
                    part_ids[part_id] = len(text_parts)
                text_parts.append(text)
        if typ in ("error", "session.error", "permission.denied"):
            errors.append(e)
        if typ == "step_finish" and isinstance(part, dict) and part.get("reason") in ("stop", "end_turn"):
            terminal = True
        if typ == "step_finish" and isinstance(part, dict) and ("tokens" in part or "cost" in part):
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
    return {"session_id": sid, "result": result, "usage_observations": usage or None,
            "actual_model": None, "usage_completeness": "partial" if usage else "unknown", "transport_terminal_observed": terminal, "usage_note": "Raw CLI observations only; no estimated tokens or billed cost. Requested model is recorded separately."}

