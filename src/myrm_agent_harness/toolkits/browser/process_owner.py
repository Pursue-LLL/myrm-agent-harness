"""Ownership stamp for browser and driver processes launched by this Python process.

Every Chromium and Playwright driver process started by the browser toolkit carries the environment
variable ``MYRM_BROWSER_OWNER=<pid>:<start_ms>`` naming the launching process. Whether a browser is a
leftover is then a fact read from the process itself (its owner no longer runs) rather than a guess
from its command line or its ancestors, so a browser that belongs to someone else is never touched.

[INPUT]
- psutil (optional): process start time, status and environment reads

[OUTPUT]
- OWNER_ENV_VAR: name of the environment variable that carries the stamp
- owner_stamp_env: the stamp of the current process as an environment mapping (empty without psutil)
- owner_stamped_environ: context manager exposing the stamp to a driver process started inside it
- OwnerState / read_owner_state: classify any process by the owner its stamp names

[POS]
Shared by the pool (stamps what it launches) and the doctor (judges what is left); neither imports the other.
"""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import psutil

OWNER_ENV_VAR = "MYRM_BROWSER_OWNER"

# psutil derives start times per platform with different rounding; a real pid reuse differs by far more.
_START_TIME_TOLERANCE_MS = 1000


class OwnerState(StrEnum):
    """What a process's stamp says about its owner."""

    UNSTAMPED = "unstamped"
    OWNER_ALIVE = "owner_alive"
    OWNER_GONE = "owner_gone"
    UNKNOWN = "unknown"


def owner_stamp_env() -> dict[str, str]:
    """The stamp naming the current process, to merge into a launched process's environment."""
    try:
        import psutil
    except ImportError:
        return {}
    return {OWNER_ENV_VAR: f"{os.getpid()}:{int(psutil.Process().create_time() * 1000)}"}


@contextlib.contextmanager
def owner_stamped_environ() -> Iterator[None]:
    """Expose the stamp in ``os.environ`` for the duration of a driver start.

    The driver inherits the environment of the process that spawns it, so the stamp must be present
    only while that spawn happens; leaving it set would hand it to every unrelated subprocess.
    """
    os.environ.update(owner_stamp_env())
    try:
        yield
    finally:
        os.environ.pop(OWNER_ENV_VAR, None)


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
        owner_started_ms = int(owner.create_time() * 1000)
    except psutil.NoSuchProcess:
        return OwnerState.OWNER_GONE
    except (psutil.Error, OSError):
        return OwnerState.UNKNOWN

    if abs(owner_started_ms - int(started_text)) <= _START_TIME_TOLERANCE_MS:
        return OwnerState.OWNER_ALIVE
    return OwnerState.OWNER_GONE
