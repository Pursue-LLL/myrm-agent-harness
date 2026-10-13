"""Real child processes carrying an ownership stamp, for orphan detection tests.

[INPUT]
- myrm_agent_harness.toolkits.browser.process_owner::OWNER_ENV_VAR / owner_stamp_env (POS: ownership stamp)
- psutil: start time of the stamped owner

[OUTPUT]
- StampedProcesses: spawns child processes with a chosen stamp and terminates them on exit
- dead_owner_stamp / live_owner_stamp: stamps naming an exited process / the running test process

[POS]
Orphan detection reads the real process table, so its tests start real processes instead of
mocking psutil. A child is a bare Python sleeper: what matters is the environment it carries,
not what kind of browser it would be.
"""

from __future__ import annotations

import functools
import os
import subprocess
import sys
import time
from types import TracebackType

import psutil

from myrm_agent_harness.toolkits.browser.process_owner import OWNER_ENV_VAR, owner_stamp_env

_CHILD_SCRIPT = (
    "import signal, sys, time\n"
    "if '--ignore-sigterm' in sys.argv:\n"
    "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "print('ready', flush=True)\n"
    "time.sleep(300)\n"
)


def live_owner_stamp() -> str:
    """Stamp naming the running test process, which is alive for the whole test."""
    return owner_stamp_env()[OWNER_ENV_VAR]


@functools.cache
def dead_owner_stamp() -> str:
    """Stamp naming a process that has already exited; it stays dead, so one is enough for the whole session."""
    owner = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.3)"])
    start_ms = int(psutil.Process(owner.pid).create_time() * 1000)
    owner.wait()
    return f"{owner.pid}:{start_ms}"


class StampedProcesses:
    """Spawns sleeping child processes and kills every one of them when the block ends."""

    def __init__(self) -> None:
        self._children: list[subprocess.Popen[str]] = []

    def spawn(
        self,
        stamp: str | None,
        *,
        ignore_sigterm: bool = False,
        extra_args: tuple[str, ...] = (),
    ) -> subprocess.Popen[str]:
        """Start a child carrying ``stamp`` (no stamp when ``None``) and return once it is running."""
        env = {key: value for key, value in os.environ.items() if key != OWNER_ENV_VAR}
        if stamp is not None:
            env[OWNER_ENV_VAR] = stamp
        args = [sys.executable, "-u", "-c", _CHILD_SCRIPT, *extra_args]
        if ignore_sigterm:
            args.append("--ignore-sigterm")
        child = subprocess.Popen(args, env=env, stdout=subprocess.PIPE, text=True)
        self._children.append(child)
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "ready"
        return child

    def wait_gone(self, child: subprocess.Popen[str], timeout_s: float = 5.0) -> bool:
        """True once ``child`` has exited, polling for up to ``timeout_s``."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if child.poll() is not None:
                return True
            time.sleep(0.02)
        return child.poll() is not None

    def __enter__(self) -> StampedProcesses:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        for child in self._children:
            if child.poll() is None:
                child.kill()
            child.wait()
            if child.stdout is not None:
                child.stdout.close()
