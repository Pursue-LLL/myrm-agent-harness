"""Unified facade suite for compact-before-send token chip and send action honesty.

[INPUT]
- compact_chip_types: CompactActionPreference, CompactBeforeSendConfig,
  CompactPreflightEstimate, SendButtonDisplaySpec.
- compact_preflight_calculator: CompactPreflightCalculator.
- send_action_label_renderer: SendActionLabelRenderer.

[OUTPUT]
- CompactBeforeSendTokenChipSuite: Master facade coordinating estimation and honest UI rendering.

[POS]
- Sub-package: myrm_agent_harness.agent.context_management.compact_chip
- Module: compact_before_send_suite.py
"""

from typing import Optional

from myrm_agent_harness.agent.context_management.compact_chip.compact_chip_types import (
    CompactActionPreference,
    CompactBeforeSendConfig,
    CompactPreflightEstimate,
    SendButtonDisplaySpec,
)
from myrm_agent_harness.agent.context_management.compact_chip.compact_preflight_calculator import (
    CompactPreflightCalculator,
)
from myrm_agent_harness.agent.context_management.compact_chip.send_action_label_renderer import (
    SendActionLabelRenderer,
)


class CompactBeforeSendTokenChipSuite:
    """Master facade providing preflight estimation and honest composer send specifications."""

    def __init__(self, config: Optional[CompactBeforeSendConfig] = None) -> None:
        self._config = config if config is not None else CompactBeforeSendConfig()
        self._calculator = CompactPreflightCalculator(self._config)
        self._renderer = SendActionLabelRenderer()

    @property
    def config(self) -> CompactBeforeSendConfig:
        """Returns the active configuration."""
        return self._config

    @property
    def calculator(self) -> CompactPreflightCalculator:
        """Returns the preflight metrics calculator."""
        return self._calculator

    @property
    def renderer(self) -> SendActionLabelRenderer:
        """Returns the display spec renderer."""
        return self._renderer

    def estimate_context(
        self,
        total_tokens: int,
        max_context_tokens: int,
        idle_seconds: float,
    ) -> CompactPreflightEstimate:
        """Computes current context occupancy and compression potential snapshot."""
        return self._calculator.calculate_estimate(
            total_tokens=total_tokens,
            max_context_tokens=max_context_tokens,
            idle_seconds=idle_seconds,
        )

    def resolve_send_spec(
        self,
        total_tokens: int,
        max_context_tokens: int,
        idle_seconds: float,
        preference: CompactActionPreference = CompactActionPreference.AUTO_COMPACT,
    ) -> SendButtonDisplaySpec:
        """Resolves full button label, tooltip, and chip spec for composer view."""
        estimate = self._calculator.calculate_estimate(
            total_tokens=total_tokens,
            max_context_tokens=max_context_tokens,
            idle_seconds=idle_seconds,
        )
        will_compact = self._calculator.resolve_will_compact(estimate, preference)
        return self._renderer.render_display_spec(estimate, preference, will_compact)

    def will_compact(
        self,
        total_tokens: int,
        max_context_tokens: int,
        idle_seconds: float,
        preference: CompactActionPreference = CompactActionPreference.AUTO_COMPACT,
    ) -> bool:
        """Returns boolean decision indicating whether next send will execute compaction."""
        estimate = self._calculator.calculate_estimate(
            total_tokens=total_tokens,
            max_context_tokens=max_context_tokens,
            idle_seconds=idle_seconds,
        )
        return self._calculator.resolve_will_compact(estimate, preference)
