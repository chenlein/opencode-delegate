"""Crash-safe CLI wall-time accounting, not token or billing accounting.

Reservations are committed with the operation intent. Only bound, complete
execution evidence can release unused time. Unknown started work exhausts the
remaining task allowance; PREPARING proves that no spawn was possible.
"""
from __future__ import annotations
import math
from pathlib import Path
from delegate_core import require, read_json, MAX_LOG, file_hash, GuardError


def seconds(value) -> float:
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value >= 0, "Invalid execution time accounting", 3)
    return float(value)


def reserve(state: dict, allowance: int, task_limit: float) -> dict:
    before = seconds(state["total_execution_seconds"])
    require(allowance >= 1 and allowance <= task_limit - before, "Invalid execution reservation", 3)
    state["total_execution_seconds"] = before + allowance
    return {"schema_version": 1, "before_seconds": before, "reserved_seconds": allowance,
            "charged_seconds": float(allowance), "task_limit_seconds": task_limit,
            "status": "reserved", "observed_seconds": None}


def settle(state: dict, execution: dict | None = None, *, never_started: bool = False,
           task_limit: float, evidence_sha256: str | None = None) -> None:
    """Idempotent settlement; caller commits this and the transition atomically."""
    op = state["operation"]
    require(op["phase"] == "run", "Only worker operations consume execution budget", 3)
    budget = op.get("budget")
    if budget is None:
        # Pre-rc.4 active operations did not reserve time; do not invent zero use.
        before = seconds(state["total_execution_seconds"])
        budget = {"schema_version": 1, "before_seconds": before, "reserved_seconds": 0,
                  "charged_seconds": max(0.0, task_limit - before),
                  "task_limit_seconds": task_limit, "status": "settled_unknown_legacy",
                  "observed_seconds": None, "note": "Legacy active run has no durable reservation"}
        op["budget"] = budget
        state["total_execution_seconds"] = before + budget["charged_seconds"]
        return
    before = seconds(budget["before_seconds"])
    if budget["status"] != "reserved":
        require(math.isclose(seconds(state["total_execution_seconds"]),
                             before + seconds(budget["charged_seconds"]), abs_tol=1e-8),
                "Settled execution accounting changed", 3)
        return
    require(math.isclose(seconds(state["total_execution_seconds"]),
                         before + seconds(budget["reserved_seconds"]), abs_tol=1e-8),
            "Execution reservation changed", 3)
    charge, observed, status = max(0.0, task_limit - before), None, "settled_unknown"
    if never_started:
        require(state["status"] == "PREPARING" and op["stage"] == "preparing",
                "Cannot prove the executor was never started", 3)
        charge, status = 0.0, "settled_not_started"
    elif execution is not None:
        require(execution.get("operation_id") == op["id"], "Execution evidence operation mismatch", 3)
        require(execution.get("contract_sha256") == state["contract_sha256"],
                "Execution evidence contract mismatch", 3)
        observed = seconds(execution.get("elapsed_seconds"))
        # Quiescence must have been checked after wait/kill, not merely inferred
        # from the leader exit code. Uncertain descendants may have kept running.
        if execution.get("process_group_quiescent") is True:
            charge, status = observed, "settled_observed"
        else:
            charge = max(charge, observed)
    budget.update(status=status, charged_seconds=charge, observed_seconds=observed,
                  evidence_sha256=evidence_sha256)
    state["total_execution_seconds"] = before + charge


def recover_accounting(task: Path, state: dict, contract: dict) -> None:
    op = state["operation"]
    if op["phase"] != "run":
        return
    execution, evidence_hash = None, None
    limit = contract.get("max_execution_seconds", 1800)
    if op.get("budget", {}).get("status", "reserved") != "reserved":
        settle(state, task_limit=limit)
        return
    never_started = state["status"] == "PREPARING" and op["stage"] == "preparing"
    if not never_started and op.get("budget") is not None:
        rel = state.get("last_attempt")
        require(isinstance(rel, str) and rel == f"attempts/{state['attempts']:03d}",
                "Invalid attempt binding for budget recovery", 3)
        path = task / rel / "execution.json"
        if path.exists() or path.is_symlink():
            # A torn/missing record cannot refund a reservation. Wrong identities
            # and changed final logs still stop recovery, preserving the evidence.
            try:
                execution = read_json(path, MAX_LOG)
                require(isinstance(execution, dict), "Malformed execution record", 3)
                evidence_hash = file_hash(path)
            except (GuardError, OSError, UnicodeError, ValueError) as exc:
                execution = None
                op["budget"]["recovery_evidence_error"] = type(exc).__name__
            if execution is not None and execution.get("process_group_quiescent") is True:
                for name, field in (("events.ndjson", "stdout_sha256"), ("stderr.log", "stderr_sha256")):
                    log = path.parent / name
                    require(log.is_file() and not log.is_symlink(),
                            "Final execution log missing or unsafe: " + name, 3)
                    require(file_hash(log) == execution.get(field),
                            "Final execution log changed: " + name, 3)
    settle(state, execution, never_started=never_started, task_limit=limit,
           evidence_sha256=evidence_hash)
