#!/usr/bin/env python3
"""Additional rc.4 delivery cases on the published operation.budget interface.

Do not replace the upstream state machine with the older standalone package.
Tests use temporary repositories and mocks; no provider or network calls.
"""
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_delegate as fixtures
import test_lifecycle_fixes as lifecycle_tests
import execution_budget as budget
import process_control as processes

d = fixtures.d


class DeliveryReconciliationTests(unittest.TestCase):
    setUp = fixtures.RunnerTests.setUp
    tearDown = fixtures.RunnerTests.tearDown
    git = fixtures.RunnerTests.git
    call = fixtures.RunnerTests.call
    init = fixtures.RunnerTests.init
    state = fixtures.RunnerTests.state
    run_worker = fixtures.RunnerTests.run_worker
    recover = lifecycle_tests.LifecycleTests.recover

    def reserved_state(self):
        state = {"total_execution_seconds": 3.0, "contract_sha256": "contract",
                 "status": "RUNNING",
                 "operation": {"id": "operation", "phase": "run", "stage": "running"}}
        state["operation"]["budget"] = budget.reserve(state, 5, 20)
        return state

    def test_unconfirmed_group_consumes_remaining_allowance_once(self):
        state = self.reserved_state()
        execution = {"operation_id": "operation", "contract_sha256": "contract",
                     "elapsed_seconds": 0.1, "process_group_quiescent": False}
        budget.settle(state, execution, task_limit=20)
        self.assertEqual(state["total_execution_seconds"], 20)
        self.assertEqual(state["operation"]["budget"]["status"], "settled_unknown")
        self.assertEqual(state["operation"]["budget"]["observed_seconds"], 0.1)
        self.assertEqual(state["operation"]["budget"]["charged_seconds"], 17)
        budget.settle(state, execution, task_limit=20)
        self.assertEqual(state["total_execution_seconds"], 20)
        # Control: a confirmed group permits accounting the measured duration.
        confirmed = self.reserved_state()
        budget.settle(confirmed, {**execution, "process_group_quiescent": True}, task_limit=20)
        self.assertAlmostEqual(confirmed["total_execution_seconds"], 3.1)
        self.assertEqual(confirmed["operation"]["budget"]["status"], "settled_observed")

    def test_observed_overrun_is_not_clamped_to_reservation_or_task_limit(self):
        state = self.reserved_state()
        execution = {"operation_id": "operation", "contract_sha256": "contract",
                     "elapsed_seconds": 25.0, "process_group_quiescent": False}
        budget.settle(state, execution, task_limit=20)
        # Prior work (3s) plus observed work (25s) must not be reported as 20s.
        self.assertEqual(state["total_execution_seconds"], 28)
        self.assertEqual(state["operation"]["budget"]["observed_seconds"], 25)
        self.assertEqual(state["operation"]["budget"]["charged_seconds"], 25)
        budget.settle(state, execution, task_limit=20)
        self.assertEqual(state["total_execution_seconds"], 28)

    def test_pending_run_cannot_launch_again_or_refund_unknown_time(self):
        self.contract.update(max_execution_seconds=20, timeout_seconds=1)
        self.assertEqual(self.init(), 0)
        with patch.object(d, "execute", side_effect=OSError("injected supervisor interruption")):
            self.run_worker(expect=2)
        self.assertEqual(self.state()["status"], "RUNNING")
        self.assertEqual(self.state()["operation"]["budget"]["status"], "reserved")
        self.assertEqual(self.state()["total_execution_seconds"], 1)
        before = (self.task / "state.json").read_bytes()
        with patch.object(d, "execute") as launch:
            self.run_worker(expect=3)
            launch.assert_not_called()
        self.assertEqual((self.task / "state.json").read_bytes(), before)
        self.recover()
        self.assertEqual(self.state()["total_execution_seconds"], 20)
        checkpoint = self.root / "checkpoint.md"
        checkpoint.write_text("Test processes stopped; no result accepted. Preserve frozen scope.\n")
        with patch.object(d, "execute") as launch:
            self.run_worker(extra=("--fresh-session", "--checkpoint", str(checkpoint)), expect=3)
            launch.assert_not_called()
        self.assertIn("Total execution time budget exhausted", self.last_err)
        self.assertEqual(self.state()["attempts"], 1)

    def test_permission_denied_signalling_never_confirms_quiescence(self):
        # Every signal is mocked; this synthetic PID never reaches the OS.
        child = SimpleNamespace(pid=os.getpgrp() + 100000, returncode=0, poll=Mock(return_value=0))
        with patch.object(processes, "group_alive", return_value=True), \
                patch.object(processes.os, "killpg", side_effect=PermissionError("injected denial")) as signal_group:
            result = processes.terminate_group(child, grace=0, kill_grace=0)
        signal_group.assert_called_once()
        self.assertFalse(result["process_group_quiescent"])
        self.assertTrue(result["leader_reaped"])
        self.assertEqual(result["signals"], [])
        self.assertTrue(result["errors"])
        self.assertIn("injected denial", result["errors"][0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
