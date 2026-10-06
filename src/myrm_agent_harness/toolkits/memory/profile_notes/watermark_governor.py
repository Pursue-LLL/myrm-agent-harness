"""Capacity watermark governor managing dual-layer memory budgets.

[INPUT]
- MemoryLayerType: USER or MEMORY
- current_content: str currently persisted in the layer
- incoming_content: str candidate content to append/insert
- WatermarkLevel, WatermarkStatus: typed status DTOs

[OUTPUT]
- CapacityWatermarkGovernor: deterministic capacity governor computing exact usage,
  watermark alert levels (SAFE, WARNING, CRITICAL, OVERFLOW), and intake allowance.

[POS]
Capacity governor enforcing Hermes memory character limits (USER <= 1375, MEMORY <= 2200),
preventing unbounded token expansion and maintaining high prompt-cache density.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.profile_notes.types import (
    MemoryLayerType,
    WatermarkLevel,
    WatermarkStatus,
)

# Standard Hermes-grade character budget constants
DEFAULT_USER_MAX_CHARS: int = 1375
DEFAULT_MEMORY_MAX_CHARS: int = 2200

# Watermark ratio thresholds
SAFE_RATIO_UPPER_BOUND: float = 0.70
WARNING_RATIO_UPPER_BOUND: float = 0.90
CRITICAL_RATIO_UPPER_BOUND: float = 1.00


class CapacityWatermarkGovernor:
    """Governor tracking character capacities and evaluating watermark thresholds."""

    def __init__(
        self,
        user_max_chars: int = DEFAULT_USER_MAX_CHARS,
        memory_max_chars: int = DEFAULT_MEMORY_MAX_CHARS,
    ) -> None:
        self._limits: dict[MemoryLayerType, int] = {
            MemoryLayerType.USER: max(1, user_max_chars),
            MemoryLayerType.MEMORY: max(1, memory_max_chars),
        }

    def get_max_chars(self, layer: MemoryLayerType) -> int:
        """Return the maximum character limit for the given layer."""
        return self._limits.get(layer, DEFAULT_MEMORY_MAX_CHARS)

    def check_watermark(
        self,
        layer: MemoryLayerType,
        current_content: str,
        incoming_content: str = "",
    ) -> WatermarkStatus:
        """Evaluate the watermark status of a memory layer with optional incoming text.

        Args:
            layer: The target memory layer (USER or MEMORY).
            current_content: Existing content in the layer.
            incoming_content: Additional text proposed to be appended.

        Returns:
            A WatermarkStatus containing usage metrics, level, and alert messages.
        """
        max_chars = self.get_max_chars(layer)
        total_chars = len(current_content) + len(incoming_content)
        usage_ratio = round(total_chars / max_chars, 4)

        if usage_ratio <= SAFE_RATIO_UPPER_BOUND:
            level = WatermarkLevel.SAFE
            warning = None
        elif usage_ratio <= WARNING_RATIO_UPPER_BOUND:
            level = WatermarkLevel.WARNING
            warning = (
                f"[{layer.value.upper()}] Capacity at {usage_ratio * 100:.1f}% "
                f"({total_chars}/{max_chars} chars). Approaching warning threshold."
            )
        elif usage_ratio <= CRITICAL_RATIO_UPPER_BOUND:
            level = WatermarkLevel.CRITICAL
            warning = (
                f"[{layer.value.upper()}] Capacity at {usage_ratio * 100:.1f}% "
                f"({total_chars}/{max_chars} chars). Critical capacity reached! Consider pruning."
            )
        else:
            level = WatermarkLevel.OVERFLOW
            warning = (
                f"[{layer.value.upper()}] Capacity OVERFLOW at {usage_ratio * 100:.1f}% "
                f"({total_chars}/{max_chars} chars). Insertion rejected by governor."
            )

        return WatermarkStatus(
            layer=layer,
            current_chars=total_chars,
            max_chars=max_chars,
            usage_ratio=usage_ratio,
            level=level,
            warning_message=warning,
        )

    def can_ingest(
        self,
        layer: MemoryLayerType,
        current_content: str,
        incoming_content: str,
    ) -> tuple[bool, WatermarkStatus]:
        """Determine if incoming content can be safely ingested without overflow.

        Returns:
            A tuple of (is_allowed: bool, status: WatermarkStatus).
        """
        status = self.check_watermark(layer, current_content, incoming_content)
        allowed = status.level != WatermarkLevel.OVERFLOW
        return allowed, status
