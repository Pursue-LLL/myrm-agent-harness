"""Domain calculator estimating context preflight compaction potential and trigger states.

[INPUT]
- compact_chip_types: CompactActionPreference, CompactBeforeSendConfig, CompactPreflightEstimate.

[OUTPUT]
- CompactPreflightCalculator: Computes preflight metrics and determines compaction execution.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.compact_chip
- Module: compact_preflight_calculator.py
"""

from myrm_agent_harness.agent.context_management.compact_chip.compact_chip_types import (
    CompactActionPreference,
    CompactBeforeSendConfig,
    CompactPreflightEstimate,
)


class CompactPreflightCalculator:
    """Calculates context pressure, idle staleness, and resolves compaction triggers."""

    def __init__(self, config: CompactBeforeSendConfig) -> None:
        self._config = config

    @property
    def config(self) -> CompactBeforeSendConfig:
        """Returns the active configuration."""
        return self._config

    def calculate_estimate(
        self,
        total_tokens: int,
        max_context_tokens: int,
        idle_seconds: float,
    ) -> CompactPreflightEstimate:
        """Calculates preflight metrics snapshot based on token budget and idle duration.

        Args:
            total_tokens: Current token occupancy of conversation messages.
            max_context_tokens: Model context window upper bound.
            idle_seconds: Elapsed duration in seconds since last assistant completion.

        Returns:
            CompactPreflightEstimate with staleness and pressure determinations.
        """
        safe_total = max(0, total_tokens)
        safe_max = max(1, max_context_tokens)
        safe_idle = max(0.0, idle_seconds)

        is_stale = safe_idle >= self._config.stale_threshold_seconds
        pressure_ceiling = int(safe_max * self._config.pressure_threshold_ratio)
        is_pressured = safe_total >= pressure_ceiling

        # Typical conversation compaction compresses ~65% of existing token volume
        compressible = int(safe_total * 0.65) if (is_stale or is_pressured) else 0

        return CompactPreflightEstimate(
            total_tokens=safe_total,
            max_context_tokens=safe_max,
            idle_seconds=safe_idle,
            estimated_compressible_tokens=compressible,
            is_stale=is_stale,
            is_pressured=is_pressured,
        )

    def resolve_will_compact(
        self,
        estimate: CompactPreflightEstimate,
        preference: CompactActionPreference,
    ) -> bool:
        """Determines whether compaction will actually execute given estimate and user preference.

        Args:
            estimate: Evaluated context estimate snapshot.
            preference: User action preference toggle.

        Returns:
            True if next message dispatch will trigger preflight compaction.
        """
        if preference == CompactActionPreference.FORCE_KEEP_FULL:
            return False

        if preference == CompactActionPreference.FORCE_COMPACT:
            return estimate.total_tokens >= self._config.min_display_tokens

        # AUTO_COMPACT
        has_trigger = estimate.is_stale or estimate.is_pressured
        has_meaningful_volume = (
            estimate.estimated_compressible_tokens >= self._config.min_display_tokens
        )
        return has_trigger and has_meaningful_volume
