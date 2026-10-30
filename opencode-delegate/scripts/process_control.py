"""Bounded cleanup of a process group created by this invocation (POSIX).

killpg(0) may include zombies. An unreaped group is conservatively unconfirmed;
we do not claim OS-wide containment of descendants that leave the group.
"""
from __future__ import annotations
import os
import signal
import subprocess
import time
from delegate_core import require


def group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def terminate_group(process: subprocess.Popen, grace: float = 2.0, kill_grace: float = 1.0) -> dict:
    pgid = process.pid
    require(pgid > 1 and pgid != os.getpgrp(), "Refusing to signal unrelated supervisor group", 3)
    actions, errors = [], []

    def wait_until_quiet(duration):
        deadline = time.monotonic() + duration
        while True:
            process.poll()  # Reap our direct child, not just check killpg(0).
            if not group_alive(pgid):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.02)

    for sig, duration in ((signal.SIGTERM, grace), (signal.SIGKILL, kill_grace)):
        process.poll()
        if not group_alive(pgid):
            break
        try:
            os.killpg(pgid, sig)
            actions.append(sig.name)
        except ProcessLookupError:
            break
        except PermissionError as exc:
            errors.append(str(exc))
            break
        if wait_until_quiet(duration):
            break
    process.poll()
    return {"signals": actions, "errors": errors,
            "process_group_quiescent": not group_alive(pgid),
            "leader_reaped": process.returncode is not None}
