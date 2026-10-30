"""Internal verification support for opencode-delegate. Standard library only."""
from __future__ import annotations
from pathlib import Path, PurePosixPath
from typing import Any
from delegate_core import GuardError, require, file_hash, read_json, MAX_LOG
from path_policy import safe_path


def verify_evidence(task: Path, s: dict) -> dict:
    require(bool(s["verification"]), "No independent verification exists", 3)
    path = task / s["verification"]["path"]
    require(file_hash(path) == s["verification"]["sha256"], "Verification report was modified", 3)
    v = read_json(path, MAX_LOG)
    for name, value in v["evidence_hashes"].items():
        require(Path(name).name == name and file_hash(path.parent / name) == value, f"Verification evidence changed: {name}", 3)
    return v


def evidence_valid(ref: str, v: dict, wt: Path, criterion: str | None = None, supports_pass: bool = False) -> bool:
    if ref == "diff":
        return v.get("diff_result", {}).get("complete") is True
    if ref.startswith("test:"):
        return any(x["id"] == ref[5:] and (criterion is None or criterion in x["criterion_ids"]) and (not supports_pass or x["passed"]) for x in v["checks"])
    if ref.startswith("file:"):
        try:
            name = safe_path(ref[5:])
            p = wt / name
            return p.is_file() and not p.is_symlink() and wt in p.resolve().parents
        except GuardError:
            return False
    return False

