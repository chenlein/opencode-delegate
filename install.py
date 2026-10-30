#!/usr/bin/env python3
"""Install an opencode-delegate release. Never overwrite without --replace."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile


def verify_package(root):
    manifest = json.loads((root / "MANIFEST.json").read_text())
    for rel, expected in manifest["sha256"].items():
        p = root / rel
        if p.is_symlink() or not p.is_file() or root.resolve() not in p.resolve().parents:
            raise RuntimeError("Missing/unsafe package file: " + rel)
        if hashlib.sha256(p.read_bytes()).hexdigest() != expected:
            raise RuntimeError("Package checksum mismatch: " + rel)
    # No hidden/unlisted payloads may ride along in the skill directory.
    allowed = {root / rel for rel in manifest["sha256"] if rel.startswith("opencode-delegate/")}
    actual = {p for p in (root / "opencode-delegate").rglob("*") if p.is_file() or p.is_symlink()}
    if actual != allowed:
        raise RuntimeError("Unexpected or missing skill files; unpack a clean release archive")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", help="Exact destination skill directory")
    parser.add_argument("--replace", action="store_true", help="Back up an existing skill, then replace it")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--backup-root", default=str(Path.home() / ".local/share/opencode-delegate/skill-backups"))
    parser.add_argument("--state-root", default=str(Path.home() / ".local/state/opencode-delegate"))
    parser.add_argument("--preserve-legacy-runner", action="store_true", help="Explicitly keep existing 2.0.0 runner backup for active legacy tasks")
    a = parser.parse_args()
    root = Path(__file__).resolve().parent
    verify_package(root)
    candidates = [Path.home() / ".agents/skills/opencode-delegate", Path.home() / ".codex/skills/opencode-delegate"]
    present = [p for p in candidates if p.exists() or p.is_symlink()]
    if a.target:
        target = Path(a.target).expanduser().absolute()
    elif len(present) > 1:
        raise RuntimeError("Both .agents and .codex copies exist. Choose --target and reconcile the other copy; no automatic deletion.")
    else:
        target = present[0] if present else candidates[0]
    if target.name != "opencode-delegate" or target.is_symlink():
        raise RuntimeError("Target must be a non-symlink directory named opencode-delegate")
    if target.exists() and not target.is_dir():
        raise RuntimeError("Target exists and is not a directory")
    backup_root = Path(a.backup_root).expanduser().absolute()
    if target == root / "opencode-delegate" or root in target.parents:
        raise RuntimeError("Refusing to install over the unpacked release")
    if target in backup_root.parents or backup_root == target or target.parent == backup_root or target.parent in backup_root.parents:
        raise RuntimeError("Backup must be outside the skill-discovery directory")
    legacy = []
    state_root = Path(a.state_root).expanduser()
    for state_file in state_root.glob("*/*/state.json"):
        state = json.loads(state_file.read_text())
        if state.get("state_schema_version", 1) == 1 and state.get("status") not in ("ACCEPTED", "REJECTED", "ARCHIVED"):
            legacy.append(str(state_file.parent))
    plan = {"legacy_active_tasks": legacy, "target": str(target), "existing": target.exists(), "backup_root": str(backup_root), "dry_run": a.dry_run}
    if a.dry_run:
        print(json.dumps(plan, indent=2)); return 0
    if legacy:
        previous = target / "scripts/delegate.py"
        if not a.preserve_legacy_runner or not previous.is_file() or 'VERSION = "2.0.0"' not in previous.read_text():
            raise RuntimeError("Active 2.0.0 tasks found. Keep/pin the old runner to recover/finish them; use --preserve-legacy-runner only when replacing that installed 2.0.0 copy. No state was changed.")
    if target.exists() and not a.replace:
        raise RuntimeError("Existing skill preserved. Inspect --dry-run, then explicitly use --replace.")
    os.umask(0o077)
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".opencode-delegate-install-", dir=str(target.parent)))
    staged_skill = stage / "opencode-delegate"
    shutil.copytree(root / "opencode-delegate", staged_skill)
    backup = None
    if target.exists():
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = backup_root / stamp / "opencode-delegate"
        backup.parent.mkdir(parents=True, exist_ok=False)
        shutil.move(str(target), str(backup))
    try:
        os.replace(staged_skill, target)
    except Exception:
        if backup is not None and not target.exists():
            shutil.move(str(backup), str(target))
        raise
    stage.rmdir()  # Only the empty temporary directory created by this invocation.
    print(json.dumps({"installed": str(target), "backup": str(backup) if backup else None,
                      "legacy_active_tasks": legacy, "legacy_runner": str(backup / "scripts/delegate.py") if legacy and backup else None, "task_state_changed": False, "opencode_config_changed": False}, indent=2))
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError) as e:
        print("ERROR: " + str(e), file=sys.stderr)
        sys.exit(2)
