"""Global action emergency kill switch circuit breaker."""

from __future__ import annotations

import logging
import time

from myrm_agent_harness.core.security.blast_radius_inspector.types import (
    ActionSurfaceDimension,
    KillSwitchState,
)

logger = logging.getLogger(__name__)


class GlobalActionKillSwitch:
    """Hardware-style emergency circuit breaker instantly terminating all outbound action surfaces."""

    def __init__(self) -> None:
        self._is_engaged: bool = False
        self._engaged_at: float | None = None
        self._engaged_by: str | None = None
        self._reason: str | None = None

    def engage(self, operator_identity: str, reason: str) -> KillSwitchState:
        """Instantly trip the circuit breaker, freezing all external communications and file writes."""
        self._is_engaged = True
        self._engaged_at = time.time()
        self._engaged_by = operator_identity
        self._reason = reason
        logger.critical(
            "GLOBAL ACTION KILL SWITCH TRIPPED by '%s'. Reason: %s",
            operator_identity,
            reason,
        )
        return self.get_state()

    def disengage(self) -> KillSwitchState:
        """Reset the circuit breaker back to normal operational status."""
        self._is_engaged = False
        self._engaged_at = None
        self._engaged_by = None
        self._reason = None
        logger.info("Global action kill switch disengaged. Normal operations restored.")
        return self.get_state()

    def get_state(self) -> KillSwitchState:
        """Retrieve current kill switch status."""
        return KillSwitchState(
            is_engaged=self._is_engaged,
            engaged_at=self._engaged_at,
            engaged_by=self._engaged_by,
            reason=self._reason,
        )

    def is_action_blocked(self, dimension: ActionSurfaceDimension) -> bool:
        """Check if an attempted action dimension is blocked by the kill switch."""
        if not self._is_engaged:
            return False

        # Under tripped kill switch, all SENDS, APIS, and FILES write mutations are fail-closed blocked
        return dimension in (
            ActionSurfaceDimension.SENDS,
            ActionSurfaceDimension.APIS,
            ActionSurfaceDimension.FILES,
            ActionSurfaceDimension.TOOLS,
        )
