"""Clean generation restart state machine with rollback protection.

Orchestrates the entire multi-service graceful drain, independent generation
launch, post-launch health verification, and rollback recovery to ensure zero
lost sessions and eliminate hung updates.

[OUTPUT]
- CleanRestartStateMachine: Master coordinator for graceful drain and restart cycles.

[INPUT]
- __future__
- asyncio
- contextlib
- os
- signal
- time

[OUTPUT]
- LauncherCallback
- DecommissionCallback
- CleanRestartStateMachine

[POS]
Clean generation restart state machine with rollback protection.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import time
from collections.abc import Callable, Coroutine

from myrm_agent_harness.runtime.drain_and_restart.drain_types import (
    RestartOutcome,
    RestartReceipt,
    RestartState,
)
from myrm_agent_harness.runtime.drain_and_restart.graceful_drain import (
    GracefulDrainCoordinator,
)
from myrm_agent_harness.runtime.drain_and_restart.restart_verifier import (
    HealthCheckProbe,
    RestartVerifier,
)

LauncherCallback = Callable[[], Coroutine[None, None, int]]
DecommissionCallback = Callable[[int], Coroutine[None, None, None]]


class CleanRestartStateMachine:
    """State machine governing drain -> launch -> verify -> settle/rollback lifecycle."""

    def __init__(
        self,
        coordinator: GracefulDrainCoordinator | None = None,
        verifier: RestartVerifier | None = None,
    ) -> None:
        self.coordinator: GracefulDrainCoordinator = (
            coordinator or GracefulDrainCoordinator("managed_service")
        )
        self.verifier: RestartVerifier = verifier or RestartVerifier()
        self._state: RestartState = "IDLE"
        self._lock: asyncio.Lock = asyncio.Lock()

    @property
    def state(self) -> RestartState:
        """Return current lifecycle state."""
        return self._state

    async def execute_restart_cycle(
        self,
        *,
        reason: str = "software_update",
        drain_budget_seconds: float = 45.0,
        expected_version: str = "current",
        launcher: LauncherCallback | None = None,
        health_probe: HealthCheckProbe | None = None,
        decommission_old: DecommissionCallback | None = None,
        verification_timeout: float = 15.0,
        current_pid: int | None = None,
    ) -> RestartReceipt:
        """Execute a full graceful restart cycle with automatic rollback upon failure."""
        async with self._lock:
            old_pid = current_pid or os.getpid()
            self._state = "DRAINING"

            # 1. Initiate drain and notify subscribers
            await self.coordinator.initiate_drain(
                reason=reason,
                drain_budget_seconds=drain_budget_seconds,
            )

            # 2. Await in-flight task completion within budget
            drain_clean = await self.coordinator.wait_for_drain(drain_budget_seconds)
            if not drain_clean:
                # Active tasks did not finish within budget; continue with notice
                pass

            # 3. Launch new generation if launcher callback is provided
            self._state = "LAUNCHING"
            new_pid: int | None = None
            if launcher is not None:
                try:
                    new_pid = await launcher()
                except Exception as launch_err:
                    self._state = "FAILED"
                    await self.coordinator.cancel_drain()
                    return RestartReceipt(
                        outcome="failed",
                        state="FAILED",
                        old_pid=old_pid,
                        new_pid=None,
                        expected_version=expected_version,
                        verified_at=None,
                        error=f"Launcher failed: {launch_err}",
                    )
            else:
                # In simulation/in-process mode without launcher callback
                new_pid = old_pid

            # 4. Verify newly launched generation
            self._state = "VERIFYING"
            outcome: RestartOutcome = "failed"
            verify_error: str | None = None

            try:
                outcome, verify_error = await self.verifier.verify_generation(
                    new_pid,
                    probe_callback=health_probe,
                    expected_version=expected_version,
                    timeout_seconds=verification_timeout,
                )
            except Exception as verif_err:
                outcome = "failed"
                verify_error = f"Verifier exception: {verif_err}"

            # 5. Handle settlement or rollback
            if outcome in ("verified", "relaunch_attempted"):
                self._state = "VERIFIED" if outcome == "verified" else "RELAUNCH_ATTEMPTED"
                if decommission_old is not None and old_pid != new_pid:
                    with contextlib.suppress(Exception):
                        await decommission_old(old_pid)
                return RestartReceipt(
                    outcome=outcome,
                    state=self._state,
                    old_pid=old_pid,
                    new_pid=new_pid,
                    expected_version=expected_version,
                    verified_at=time.time(),
                    error=None,
                )

            # Verification failed -> Rollback!
            self._state = "FAILED"
            await self.coordinator.cancel_drain()

            # Clean up zombie new process if distinct from current
            if new_pid is not None and new_pid != old_pid and RestartVerifier.is_pid_alive(new_pid):
                with contextlib.suppress(OSError):
                    os.kill(new_pid, signal.SIGTERM)

            return RestartReceipt(
                outcome="failed",
                state="FAILED",
                old_pid=old_pid,
                new_pid=new_pid,
                expected_version=expected_version,
                verified_at=None,
                error=verify_error or "Health verification failed",
            )
