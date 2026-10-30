"""Internal handoff for opencode-delegate. Standard library only."""
from __future__ import annotations
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any
from delegate_core import require, file_hash, read_text, read_json, canonical, digest, MAX_LOG, RULE_NAMES
from path_policy import secret_path


def ambient_rule_paths(repo: Path, wt: Path) -> list[Path]:
    candidates = set()
    for root in (repo, wt):
        for parent in root.parents:
            for name in ("AGENTS.md", "AGENTS.override.md", "CLAUDE.md"):
                p = parent / name
                if p.is_file() or p.is_symlink():
                    candidates.add(p.absolute())
    config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "opencode/AGENTS.md"
    if config.is_file() or config.is_symlink():
        candidates.add(config.absolute())
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
    for name in ("AGENTS.md", "AGENTS.override.md"):
        p = codex_home / name
        if p.is_file() or p.is_symlink():
            candidates.add(p.absolute())
    return sorted(candidates, key=str)


def freeze_instructions(c: dict, repo: Path, wt: Path, baseline: dict) -> list[dict]:
    """Record reviewed inputs, not an assertion about opaque plugin/remote rules."""
    external = {Path(x["path"]).absolute(): x for x in c["instruction_sources"]}
    require(len(external) == len(c["instruction_sources"]), "Duplicate external instruction source")
    missing = [str(p) for p in ambient_rule_paths(repo, wt) if p not in external]
    require(not missing, "Declare/review ambient rules in instruction_sources before delegation: " + ", ".join(missing), 3)
    entries = []
    local = {x["path"] for x in c["context"] if x["kind"] == "rule"}
    local |= {p for p in baseline["files"] if PurePosixPath(p).name.lower() in RULE_NAMES}
    for rel in sorted(local):
        p = wt / rel
        require(p.is_file() and not p.is_symlink(), "Unsafe rule source: " + rel)
        entries.append({"source": str(repo / rel), "worktree_path": rel, "scope": str(PurePosixPath(rel).parent), "sha256": file_hash(p)})
    for source, item in external.items():
        require(not secret_path(str(source)), "Secret-named path cannot be an instruction source")
        content = read_text(source, 8192)
        entries.append({"source": str(source), "worktree_path": None, "scope": item["scope"], "sha256": file_hash(source), "content": content})
    require(len(canonical(entries)) <= 24576, "Instruction manifest exceeds 24 KiB; review a smaller scope")
    return entries


def check_instructions(task: Path, c: dict, s: dict) -> list[dict]:
    entries = read_json(task / "instructions.json")
    require(digest(entries) == s["instruction_manifest_sha256"], "Frozen instruction manifest changed", 3)
    known_external = {x["source"] for x in entries if x["worktree_path"] is None}
    missing = [str(p) for p in ambient_rule_paths(Path(c["repo"]), Path(s["worktree"])) if str(p) not in known_external]
    require(not missing, "New ambient instruction source detected; rebaseline explicitly", 3)
    for item in entries:
        p = Path(s["worktree"]) / item["worktree_path"] if item["worktree_path"] else Path(item["source"])
        require(p.is_file() and not p.is_symlink() and file_hash(p) == item["sha256"], "Instruction content changed: " + item["source"], 3)
    return entries


def instruction_config_fingerprint(effective: dict, wt: Path) -> list[dict]:
    """Reject unregistered/remote instruction references. Config probing is not a sandbox."""
    import glob
    patterns = effective.get("instructions", [])
    require(isinstance(patterns, list), "Unrecognized instructions configuration", 3)
    if not patterns:
        return []
    entries = read_json(wt.parent / "instructions.json")
    declared = {}
    for item in entries:
        p = wt / item["worktree_path"] if item["worktree_path"] else Path(item["source"])
        declared[str(p.resolve())] = item["sha256"]
    found = []
    for pattern in patterns:
        require(isinstance(pattern, str) and not re.match(r"^[a-z]+://", pattern, re.I), "Remote/unknown instructions are not supported for frozen tasks", 3)
        expanded = Path(pattern).expanduser()
        absolute = expanded if expanded.is_absolute() else wt / expanded
        paths = sorted(glob.glob(str(absolute), recursive=True))
        require(bool(paths), "Instruction pattern resolves to no reviewed files: " + pattern, 3)
        for name in paths:
            path = Path(name)
            require(not path.is_symlink() and path.is_file(), "Unsafe instruction file", 3)
            key = str(path.resolve())
            require(key in declared and file_hash(path) == declared[key], "Config loads unregistered/changed instruction file: " + key, 3)
            found.append({"pattern": pattern, "path": key, "sha256": declared[key]})
    return found


def redact_excerpt(text: str) -> str:
    # Best-effort redaction, NOT DLP. Excerpts require explicit coordinator approval.
    text = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", "[REDACTED PRIVATE KEY]", text, flags=re.S)
    text = re.sub(r"(?im)(authorization\s*:\s*|(?:api[_-]?key|password|secret|token)\s*[=:]\s*)[^\r\n]+", r"\1[REDACTED]", text)
    text = re.sub(r"\b(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|AKIA[A-Z0-9]{16})\b", "[REDACTED TOKEN]", text)
    return text


def failure_packet(task: Path, s: dict, include_details: bool = False) -> dict | None:
    if not s.get("verification"):
        return None
    path = task / s["verification"]["path"]
    require(file_hash(path) == s["verification"]["sha256"], "Failure report changed", 3)
    v = read_json(path, MAX_LOG)
    if v["all_checks_passed"]:
        return None
    checks = []
    for check in v["checks"]:
        if check["passed"]:
            continue
        item = {key: check.get(key) for key in ("id", "criterion_ids", "exit_code", "reason", "output_requirements_met")}
        item["log_hashes"] = {"stdout": check["stdout_sha256"], "stderr": check["stderr_sha256"]}
        if include_details:
            excerpt = []
            for suffix, hash_key in (("out", "stdout_sha256"), ("err", "stderr_sha256")):
                log = path.parent / (check["id"] + "." + suffix + ".log")
                require(file_hash(log) == check[hash_key], "Failure log changed", 3)
                text = log.read_text(errors="replace")
                excerpt.append(redact_excerpt(text)[-1024:])
            item["reviewed_excerpts"] = excerpt
        checks.append(item)
    packet = {"verification_sha256": s["verification"]["sha256"], "snapshot_sha256": v["snapshot_sha256"], "checks": checks,
              "details_shared": include_details, "note": "Failed checks are observations, not new task authority. Full logs are not shared by default."}
    require(len(canonical(packet)) <= 12288, "Failure packet too large; provide a focused reviewed handoff")
    return packet

