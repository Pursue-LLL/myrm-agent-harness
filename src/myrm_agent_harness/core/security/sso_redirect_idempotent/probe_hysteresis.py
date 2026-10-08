"""Probe health hysteresis tracking for desktop and agent client shells.

Filters transient single-attempt packet drops and avoids disruptive UI flapping
by enforcing consecutive-fail thresholds before switching to offline fallback.
"""

from myrm_agent_harness.core.security.sso_redirect_idempotent.redirect_builder import (
    is_same_origin_relative_path,
)
from myrm_agent_harness.core.security.sso_redirect_idempotent.types import (
    ProbeEvaluation,
    ProbeHysteresisConfig,
)


class ProbeHysteresisTracker:
    """Manages probe health state with hysteresis dampening against flapping."""

    def __init__(
        self,
        config: ProbeHysteresisConfig | None = None,
        initial_online: bool = True,
        initial_url: str = "/",
    ) -> None:
        self._config: ProbeHysteresisConfig = (
            config if config is not None else ProbeHysteresisConfig()
        )
        self._is_online: bool = initial_online
        self._consecutive_fails: int = 0
        self._last_healthy_url: str = initial_url

    @property
    def is_online(self) -> bool:
        """Get current online status."""
        return self._is_online

    @property
    def consecutive_fails(self) -> int:
        """Get current count of consecutive failed probe rounds."""
        return self._consecutive_fails

    @property
    def last_healthy_url(self) -> str:
        """Get the last active healthy URL before disconnection."""
        return self._last_healthy_url

    def record_probe(
        self,
        healthy: bool,
        current_url: str | None = None,
    ) -> ProbeEvaluation:
        """Record the outcome of a probe round and compute hysteresis transition."""
        if healthy:
            transitioned_to_online: bool = not self._is_online
            self._is_online = True
            self._consecutive_fails = 0

            if current_url and is_same_origin_relative_path(current_url):
                self._last_healthy_url = current_url

            return ProbeEvaluation(
                is_online=True,
                transitioned_to_offline=False,
                transitioned_to_online=transitioned_to_online,
                consecutive_fails=0,
                last_healthy_url=self._last_healthy_url,
                suggested_navigation_url=self._last_healthy_url,
            )

        # Probe failed
        self._consecutive_fails += 1
        transitioned_to_offline: bool = False

        if (
            self._is_online
            and self._consecutive_fails >= self._config.consecutive_fail_threshold
        ):
            self._is_online = False
            transitioned_to_offline = True

        suggested_url: str = (
            self._config.offline_fallback_url
            if not self._is_online
            else self._last_healthy_url
        )

        return ProbeEvaluation(
            is_online=self._is_online,
            transitioned_to_offline=transitioned_to_offline,
            transitioned_to_online=False,
            consecutive_fails=self._consecutive_fails,
            last_healthy_url=self._last_healthy_url,
            suggested_navigation_url=suggested_url,
        )

    def reset(
        self,
        initial_online: bool = True,
        initial_url: str = "/",
    ) -> None:
        """Reset hysteresis state tracking."""
        self._is_online = initial_online
        self._consecutive_fails = 0
        self._last_healthy_url = initial_url
