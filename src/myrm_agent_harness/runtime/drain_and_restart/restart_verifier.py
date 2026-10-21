"""Independent health verification prober for clean service generations.

Implements the Hermes Agent conservative restart verification model to
guarantee a restarted process is alive and healthy before decommissioning
the prior generation.

[OUTPUT]
- RestartVerifier: Prober for process liveness and health endpoint validation.

[INPUT]
- __future__
- asyncio
- os
- time
- collections

[OUTPUT]
- HealthCheckProbe
- RestartVerifier

[POS]
Independent health verification prober for clean service generations.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable, Coroutine

from myrm_agent_harness.runtime.drain_and_restart.drain_types import (
    RestartOutcome,
)

HealthCheckProbe = Callable[[int], Coroutine[None, None, tuple[bool, str | None]]]


class RestartVerifier:
    """Verifies that a newly launched service generation is running and healthy."""

    @staticmethod
    def is_pid_alive(pid: int) -> bool:
        """Check if target process ID is alive using POSIX signal probe."""
        if pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # Process exists but owned by another user; still alive
            return True
        except OSError:
            return False

    async def verify_generation(
        self,
        new_pid: int | None,
        *,
        probe_callback: HealthCheckProbe | None = None,
        expected_version: str | None = None,
        timeout_seconds: float = 15.0,
        probe_interval: float = 0.2,
    ) -> tuple[RestartOutcome, str | None]:
        """Poll and verify that new_pid is healthy before decommissioning old process.

        Returns:
            tuple[RestartOutcome, str | None]: (outcome, detail_message)
        """
        if new_pid is None or not self.is_pid_alive(new_pid):
            return "failed", f"New generation process PID {new_pid} is not alive"

        # If no specific probe is configured, we observe process liveness only
        if probe_callback is None:
            return "relaunch_attempted", (
                f"PID {new_pid} observed alive, but no independent health probe configured"
            )

        start_time = time.time()
        last_error: str | None = None

        while (time.time() - start_time) < timeout_seconds:
            if not self.is_pid_alive(new_pid):
                return "failed", f"New process PID {new_pid} terminated during health probing"

            try:
                healthy, version_detected = await probe_callback(new_pid)
                if healthy:
                    if expected_version is not None and version_detected != expected_version:
                        return (
                            "failed",
                            f"Version mismatch: expected '{expected_version}', "
                            f"detected '{version_detected}'",
                        )
                    return "verified", None
                last_error = f"Probe reported unhealthy: detected version={version_detected}"
            except Exception as err:
                last_error = f"Health check raised exception: {err}"

            await asyncio.sleep(probe_interval)

        return (
            "failed",
            f"Health check timed out after {timeout_seconds}s. Last error: {last_error}",
        )
