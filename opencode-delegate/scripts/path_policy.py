"""Internal path policy for opencode-delegate. Standard library only."""
from __future__ import annotations
from pathlib import Path, PurePosixPath
import re
from typing import Any
from delegate_core import require, canonical, PROTECTED_NAMES, PROTECTED_PARTS, SECRET_NAMES


def safe_path(text: str, directory: bool = False) -> str:
    require(isinstance(text, str) and bool(text), "Path must be nonempty text")
    require(not any(ord(c) < 32 for c in text), f"Control character in path: {text!r}")
    require(not any(c in text for c in "\\*?[]{}"), f"No wildcards/backslashes in paths: {text}")
    raw = text[:-1] if text.endswith("/") else text
    p = PurePosixPath(raw)
    require(not p.is_absolute() and raw not in ("", ".") and all(x not in ("", ".", "..") for x in raw.split("/")), f"Unsafe path: {text}")
    require(directory or not text.endswith("/"), f"File path required: {text}")
    return text


def matches(path: str, entries: list[str]) -> bool:
    return any(path.startswith(x) if x.endswith("/") else path == x for x in entries)


def paths_overlap(a: str, b: str) -> bool:
    """Exact, ancestor and descendant intersection, never naive string prefixes."""
    pa, pb = PurePosixPath(a.rstrip("/")), PurePosixPath(b.rstrip("/"))
    return pa == pb or (a.endswith("/") and pa in pb.parents) or (b.endswith("/") and pb in pa.parents)


def secret_path(path: str) -> bool:
    parts = [x.lower() for x in PurePosixPath(path).parts]
    name = parts[-1] if parts else ""
    return bool(set(parts) & {".ssh", ".aws"}) or name in SECRET_NAMES or name == ".env" or name.startswith(".env.") or name.endswith((".pem", ".key", ".p12", ".pfx"))


def assert_clean_visibility(snap: dict) -> None:
    suspicious = [p for p, item in snap["files"].items() if secret_path(p) or item["kind"] == "symlink"]
    require(not suspicious, "Workspace contains secret-named files or symlinks; use a curated, secret-free checkout: " + ", ".join(suspicious[:12]), 3)


def protected(path: str) -> bool:
    parts = [p.lower() for p in PurePosixPath(path).parts]
    name = parts[-1] if parts else ""
    return (bool(set(parts) & PROTECTED_PARTS) or name in PROTECTED_NAMES or name in SECRET_NAMES
            or secret_path(path))


def validate_contract(c: Any) -> dict:
    require(isinstance(c, dict), "Contract must be an object")
    fields = {"verification_sources", "instruction_sources", "max_execution_seconds", "schema_version", "project_id", "task_id", "environment", "repo", "mode", "objective", "non_goals", "allowed_paths", "protected_paths", "context", "acceptance", "checks", "verification_artifacts", "model", "variant", "timeout_seconds", "max_attempts"}
    require(not set(c) - fields, f"Unknown contract fields: {sorted(set(c) - fields)}")
    for name in ["schema_version", "project_id", "task_id", "environment", "repo", "mode", "objective", "allowed_paths", "acceptance", "checks", "model"]:
        require(name in c, f"Missing contract field: {name}")
    require(c["schema_version"] == 2, "schema_version must be 2")
    for name in ("project_id", "task_id"):
        require(isinstance(c[name], str) and re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", c[name]) is not None, f"Invalid {name}")
    for name in ("environment", "objective", "model", "repo"):
        require(isinstance(c[name], str) and bool(c[name].strip()), f"Invalid {name}")
    require(Path(c["repo"]).is_absolute(), "repo must be absolute")
    require(re.fullmatch(r"[A-Za-z0-9_.:-]+/[A-Za-z0-9_.:/#-]+", c["model"]) is not None, "model must be an explicit provider/model identifier")
    require(c["mode"] in ("analyze", "implement"), "mode must be analyze or implement")
    for name in ("allowed_paths", "protected_paths", "verification_artifacts"):
        c.setdefault(name, [])
        require(isinstance(c[name], list) and all(isinstance(p, str) for p in c[name]), f"{name} must be a list of paths")
        require(len(c[name]) == len(set(c[name])), f"Duplicate {name}")
        for p in c[name]:
            safe_path(p, True)
    require(c["mode"] != "analyze" or not c["allowed_paths"], "analyze requires empty allowed_paths")
    require(c["mode"] != "implement" or bool(c["allowed_paths"]), "implement requires allowed_paths")
    for p in c["allowed_paths"] + c["verification_artifacts"]:
        require(not protected(p.rstrip("/")) and not matches(p.rstrip("/"), c["protected_paths"]), f"Cannot authorize protected path: {p}")
    c.setdefault("non_goals", [])
    require(isinstance(c["non_goals"], list) and all(isinstance(x, str) for x in c["non_goals"]), "non_goals must be strings")
    c.setdefault("context", [])
    require(isinstance(c["context"], list), "context must be a list")
    for item in c["context"]:
        require(isinstance(item, dict) and set(item) <= {"path", "purpose", "kind"} and "path" in item and "purpose" in item, "context entries require path/purpose; optional kind")
        safe_path(item["path"])
        require(isinstance(item["purpose"], str), "context purpose must be text")
        item.setdefault("kind", "reference")
        require(item["kind"] in ("reference", "rule"), "context kind must be reference or rule")
        if item["kind"] == "rule" and item["path"] not in c["protected_paths"]:
            c["protected_paths"].append(item["path"])
    c.setdefault("verification_sources", [])
    require(isinstance(c["verification_sources"], list), "verification_sources must be a path list")
    for path in c["verification_sources"]:
        safe_path(path, True)
        if path not in c["protected_paths"]:
            c["protected_paths"].append(path)
    c.setdefault("instruction_sources", [])
    require(isinstance(c["instruction_sources"], list), "instruction_sources must be a list")
    for item in c["instruction_sources"]:
        require(isinstance(item, dict) and set(item) == {"path", "scope"}, "instruction_sources entries require absolute path and scope")
        require(isinstance(item["path"], str) and Path(item["path"]).is_absolute(), "External instruction path must be absolute")
        require(isinstance(item["scope"], str) and bool(item["scope"].strip()), "Instruction scope required")
    for path in c["allowed_paths"]:
        require(not matches(path.rstrip("/"), c["protected_paths"]) and path.rstrip("/") not in {x.rstrip("/") for x in c["protected_paths"]}, "Allowed path is a protected rule/verification source")
    for path in c["verification_artifacts"]:
        require(path.endswith("/"), "verification_artifacts must be explicit directory/ prefixes")
        require(not any(paths_overlap(path, other) for other in c["allowed_paths"] + c["protected_paths"]), "Verification artifact paths overlap source scope")
    require(isinstance(c["acceptance"], list) and c["acceptance"], "At least one acceptance criterion required")
    ids = []
    for item in c["acceptance"]:
        require(isinstance(item, dict) and set(item) == {"id", "description"}, "acceptance entries require id/description")
        require(isinstance(item["id"], str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", item["id"]) is not None, "Invalid criterion id")
        require(isinstance(item["description"], str) and bool(item["description"].strip()), "Empty criterion")
        ids.append(item["id"])
    require(len(ids) == len(set(ids)), "Duplicate acceptance ids")
    require(isinstance(c["checks"], list), "checks must be a list")
    check_ids = []
    for item in c["checks"]:
        require(isinstance(item, dict) and set(item) <= {"id", "argv", "cwd", "timeout_seconds", "criterion_ids", "output_contains", "trusted_inline"}, "Invalid check fields")
        require(all(k in item for k in ("id", "argv", "criterion_ids")), "Checks require id, argv, criterion_ids")
        require(isinstance(item["id"], str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", item["id"]) is not None, "Invalid check id")
        require(isinstance(item["argv"], list) and bool(item["argv"]) and all(isinstance(x, str) and "\0" not in x for x in item["argv"]), "check argv must be a nonempty string array")
        require(isinstance(item["criterion_ids"], list) and bool(item["criterion_ids"]) and all(i in ids for i in item["criterion_ids"]), "Invalid check criterion_ids")
        item.setdefault("trusted_inline", False)
        require(type(item["trusted_inline"]) is bool, "trusted_inline must be boolean")
        if item["trusted_inline"]:
            require(len(item["argv"]) == 3 and item["argv"][:2] == ["{python}", "-c"], "trusted_inline only permits a reviewed Python -c command frozen in the contract")
        else:
            require(bool(c["verification_sources"]), "External test commands require verification_sources (tests, fixtures and entrypoints reviewed by coordinator)")
        item.setdefault("cwd", ".")
        if item["cwd"] != ".":
            safe_path(item["cwd"])
        item.setdefault("timeout_seconds", 120)
        require(type(item["timeout_seconds"]) is int and 1 <= item["timeout_seconds"] <= 3600, "Invalid check timeout")
        item.setdefault("output_contains", [])
        require(isinstance(item["output_contains"], list) and all(isinstance(x, str) for x in item["output_contains"]), "output_contains must be strings")
        check_ids.append(item["id"])
    require(len(check_ids) == len(set(check_ids)), "Duplicate check ids")
    c.setdefault("max_execution_seconds", 1800)
    require(type(c["max_execution_seconds"]) is int and 1 <= c["max_execution_seconds"] <= 72000, "Invalid total execution time budget")
    c.setdefault("timeout_seconds", 600)
    c.setdefault("max_attempts", 3)
    require(type(c["timeout_seconds"]) is int and 1 <= c["timeout_seconds"] <= 7200, "Invalid task timeout")
    require(type(c["max_attempts"]) is int and 1 <= c["max_attempts"] <= 10, "max_attempts must be 1..10")
    if "variant" in c:
        require(isinstance(c["variant"], str) and re.fullmatch(r"[A-Za-z0-9_.-]+", c["variant"]) is not None, "Invalid variant")
    require(len(canonical(c)) <= 24576, "Contract exceeds 24 KiB; use file references instead of conversation dumps")
    return c

