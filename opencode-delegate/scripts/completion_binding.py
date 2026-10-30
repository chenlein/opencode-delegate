"""Freeze the successful worker identity across independent verification retries."""
from __future__ import annotations
from pathlib import Path
from delegate_core import require, file_hash, read_json, MAX_LOG


def checked_worker_completion(task: Path, contract: dict, state: dict) -> dict:
    binding = state.get("worker_completion")
    require(isinstance(binding, dict),
            "No bound completed worker result; preserve old task and use its original runner", 3)
    expected = f"attempts/{state['attempts']:03d}/worker-result.json"
    require(binding.get("path") == expected and binding.get("attempt") == state["attempts"]
            and binding.get("contract_sha256") == state["contract_sha256"]
            and binding.get("instruction_manifest_sha256") == state["instruction_manifest_sha256"],
            "Completed worker binding changed", 3)
    path = task / expected
    require(file_hash(path) == binding.get("sha256"), "Completed worker result changed", 3)
    value = read_json(path, MAX_LOG)
    require(value["result"]["task_id"] == contract["task_id"]
            and value["result"]["status"] == "complete"
            and value["session_id"] == state["session_id"],
            "Completed worker identity/status mismatch", 3)
    return binding
