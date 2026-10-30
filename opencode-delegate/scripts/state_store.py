"""Internal state store for opencode-delegate. Standard library only."""
from __future__ import annotations
import contextlib
import fcntl
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any
from delegate_core import (GuardError, require, read_json, atomic_json, digest, now, VERSION, STATE_SCHEMA_VERSION, MAX_LOG, SCAN_METRICS)


@contextlib.contextmanager
def locked(task: Path):
    require(task.is_dir() and not task.is_symlink(), "Task directory is missing/symlinked")
    path = task / ".lock"
    require(not path.is_symlink(), "Task lock is symlinked")
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise GuardError("Task is locked by another runner; do not remove the lock file", 3) from e
        yield
    finally:
        os.close(fd)


def load(task: Path, allow_legacy: bool = False) -> tuple[dict, dict, dict, dict]:
    s = read_json(task / "state.json", MAX_LOG)
    schema = s.get("state_schema_version", 1)
    require(schema in (1, STATE_SCHEMA_VERSION), "Unknown task state schema; no automatic rewrite")
    if schema == 1:
        require(s.get("runner_version") == "2.0.0", "Unknown legacy state")
        require(allow_legacy, "Legacy 2.0.0 task is read-only in this runner. Use the backed-up 2.0.0 runner to recover/finish, then create a new task; state was not changed", 3)
    c = read_json(task / "contract.json")
    require(digest(c) == s["contract_sha256"], "Frozen task contract changed; create a new task")
    base = read_json(task / "baseline.json", 64 * 1024 * 1024)
    cp_path = "checkpoint.json" if schema == 1 else "checkpoints/" + s["checkpoint_sha256"] + ".json"
    require(re.fullmatch(r"[a-f0-9]{64}", s["checkpoint_sha256"]) is not None, "Invalid checkpoint address")
    cp = read_json(task / cp_path, 64 * 1024 * 1024)
    require(base["sha256"] == s["base_sha256"] and digest({k: v for k, v in base.items() if k != "sha256"}) == base["sha256"], "Baseline manifest changed")
    require(cp["sha256"] == s["checkpoint_sha256"] and digest({k: v for k, v in cp.items() if k != "sha256"}) == cp["sha256"], "Checkpoint manifest changed")
    require(Path(s["worktree"]) == task / "worktree", "Unexpected worktree mapping")
    return c, s, base, cp


def save(task: Path, state: dict, cp: dict | None = None) -> None:
    """Immutable snapshots + single atomic state commit; orphan snapshots are harmless."""
    candidate = dict(state)
    candidate.update(updated_at=now(), last_writer_version=VERSION, generation=candidate.get("generation", 0) + 1)
    require(candidate.get("state_schema_version") == STATE_SCHEMA_VERSION, "Refusing to rewrite legacy/unknown state")
    if cp is not None:
        address = cp["sha256"]
        require(digest({k: v for k, v in cp.items() if k != "sha256"}) == address, "Invalid checkpoint hash")
        path = task / "checkpoints" / (address + ".json")
        if path.exists():
            require(read_json(path, 64 * 1024 * 1024) == cp, "Immutable checkpoint was modified")
        else:
            atomic_json(path, cp)
        candidate["checkpoint_sha256"] = address
    if SCAN_METRICS:
        metrics = dict(candidate.get("scan_totals", {"calls": 0, "files": 0, "bytes": 0, "seconds": 0.0}))
        for item in SCAN_METRICS:
            metrics["calls"] += 1; metrics["files"] += item["files"]; metrics["bytes"] += item["bytes"]
            metrics["seconds"] = round(metrics["seconds"] + item["elapsed_seconds"], 6)
        candidate["scan_totals"] = metrics
    if (task / "state.json").exists():
        atomic_json(task / "state.previous.json", read_json(task / "state.json", MAX_LOG))
    atomic_json(task / "state.json", candidate)
    state.clear(); state.update(candidate)
    SCAN_METRICS.clear()

