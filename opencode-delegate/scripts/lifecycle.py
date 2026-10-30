"""Durable operation intent. External side effects never precede their intent."""
from __future__ import annotations
import uuid
from pathlib import Path
from delegate_core import require, read_json, digest, now
from state_store import save


def begin(task: Path, state: dict, checkpoint: dict, phase: str, status: str, details: dict | None = None) -> None:
    require(phase in ("run", "verify", "cleanup"), "Unknown operation phase")
    state["operation"] = {"id": uuid.uuid4().hex, "phase": phase, "stage": "preparing",
                          "start_sha256": checkpoint["sha256"], "started_at": now(),
                          "prior_status": state["status"], "errors": []}
    require(not set(details or {}) & set(state["operation"]), "Reserved operation field")
    state["operation"].update(details or {})
    state.update(status=status, process_pid=None)
    save(task, state, checkpoint)


def start_snapshot(task: Path, state: dict) -> dict:
    op = state.get("operation")
    require(isinstance(op, dict) and op.get("phase") in ("run", "verify", "cleanup"),
            "No durable operation phase. Preserve this legacy task and reconcile using its original runner; do not guess the phase", 3)
    address = op.get("start_sha256", "")
    require(isinstance(address, str) and len(address) == 64 and all(x in "0123456789abcdef" for x in address), "Invalid operation checkpoint")
    cp = read_json(task / "checkpoints" / (address + ".json"), 64 * 1024 * 1024)
    require(cp.get("sha256") == address and digest({k: v for k, v in cp.items() if k != "sha256"}) == address,
            "Operation checkpoint changed", 3)
    return cp
