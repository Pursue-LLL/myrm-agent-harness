"""Ownership stamp for the browser processes launched by this Python process.

Every Chromium process started by the browser toolkit carries the environment variable
``MYRM_BROWSER_OWNER=<pid>:<start_ms>`` naming the launching process, and passes it on to whatever it
starts: its helpers, and possibly an application it hands a link or a file to. The stamp therefore
proves who launched a process, not what it is. Whether a browser is a leftover is then a fact read from the process
itself (its owner no longer runs, and it is a Chromium binary) rather than a guess from its command line
or its ancestors, so a browser that belongs to someone else is never touched.

[INPUT]
- psutil (optional): process start time, boot time, status and environment reads

[OUTPUT]
- OWNER_ENV_VAR: name of the environment variable that carries the stamp
- owner_stamp_env: the stamp of the current process as an environment mapping (empty without psutil)
- OwnerState / read_owner_state: classify any process by the owner its stamp names

[POS]
Shared by the pool and the doctor probe (stamp what they launch) and the orphan check (judges what is left);
the pool and the orphan check do not import each other.
"""

from __future__ import annotations

import os
import sys
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psutil

OWNER_ENV_VAR = "MYRM_BROWSER_OWNER"

# psutil derives start times per platform with different rounding; a real pid reuse differs by far more.
_START_TIME_TOLERANCE_MS = 1000

# On Linux psutil reports a start time as boot time plus ticks since boot, and the boot time follows the
# wall clock (NTP steps, a VM resumed with a corrected clock); elsewhere the start time is a fixed instant.
_START_TIMES_FOLLOW_WALL_CLOCK = sys.platform.startswith("linux")


class OwnerState(StrEnum):
    """What a process's stamp says about its owner."""

    UNSTAMPED = "unstamped"
    OWNER_ALIVE = "owner_alive"
    OWNER_GONE = "owner_gone"
    UNKNOWN = "unknown"


def _start_ms(proc: psutil.Process) -> int:
    """Start time of ``proc`` in milliseconds, comparable across system clock adjustments."""
    import psutil

    started = proc.create_time()
    if _START_TIMES_FOLLOW_WALL_CLOCK:
        started -= psutil.boot_time()
    return int(started * 1000)


def owner_stamp_env() -> dict[str, str]:
    """The stamp naming the current process, to merge into a launched process's environment."""
    try:
        import psutil
    except ImportError:
        return {}
    return {OWNER_ENV_VAR: f"{os.getpid()}:{_start_ms(psutil.Process())}"}


def read_owner_state(proc: psutil.Process) -> OwnerState:
    """Classify ``proc`` by its stamp; anything that cannot be established as a gone owner is not ``OWNER_GONE``."""
    import psutil

    try:
        stamp = proc.environ().get(OWNER_ENV_VAR)
    except (psutil.Error, OSError):
        return OwnerState.UNKNOWN
    if stamp is None:
        return OwnerState.UNSTAMPED

    owner_pid_text, _, started_text = stamp.partition(":")
    if not (owner_pid_text.isdecimal() and started_text.isdecimal()) or int(owner_pid_text) == 0:
        return OwnerState.UNKNOWN

    try:
        owner = psutil.Process(int(owner_pid_text))
        if owner.status() == psutil.STATUS_ZOMBIE:
            return OwnerState.OWNER_GONE
        owner_started_ms = _start_ms(owner)
    except psutil.NoSuchProcess:
        return OwnerState.OWNER_GONE
    except (psutil.Error, OSError):
        return OwnerState.UNKNOWN

    if abs(owner_started_ms - int(started_text)) <= _START_TIME_TOLERANCE_MS:
        return OwnerState.OWNER_ALIVE
    return OwnerState.OWNER_GONE
