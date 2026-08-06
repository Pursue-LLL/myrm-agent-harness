"""Types for agent-loop MoA advisor overlay (distinct from standalone consensus mode).

[POS]
See module docstring.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from myrm_agent_harness.toolkits.llms.consensus.types import PrivacyFilterMode

MoAFanoutMode = Literal["user_turn", "per_iteration", "every_n"]


@dataclass(frozen=True, slots=True)
class MoAOverlayConfig:
    """Execution parameters for agent-loop advisor fan-out.

    Separate SSOT from ``engineParams.consensus`` (chat-lane standalone MoA).
    Reference models are supplied as ``BaseChatModel`` instances to the
    middleware factory; this object carries fan-out and call parameters only.
    """

    fanout: MoAFanoutMode = "user_turn"
    every_n: int = 2
    reference_temperature: float = 0.6
    min_successful: int = 1
    timeout_per_model: float = 120.0
    timeout_total: float = 300.0
    max_retries_per_model: int = 2
    reference_max_tokens: int | None = 600
    reference_reasoning_effort: str | None = "low"
    privacy_filter: PrivacyFilterMode = "off"


__all__ = [
    "MoAFanoutMode",
    "MoAOverlayConfig",
    "PrivacyFilterMode",
]
