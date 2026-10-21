"""Dual-layer Profile and Working Notes memory budget and intake typing.

[INPUT]
- None (Self-contained foundational dataclasses and StrEnums)

[OUTPUT]
- MemoryLayerType: Enum distinguishing USER (user profile) and MEMORY (agent notes)
- WatermarkLevel: SAFE, WARNING, CRITICAL, OVERFLOW
- GarbageCategory: Classification of rejected intake content
- IntakeDecision: Structured decision on whether content can be saved to memory
- WatermarkStatus: Capacity usage metrics, ratio, and threshold alerts

[POS]
Foundational types for DualLayerProfileMemoryBudgetAndGarbagePurgeGuard, enforcing
Hermes-grade memory purity, strict capacity budgets, and dual-layer organization.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MemoryLayerType(StrEnum):
    """Memory layer classification for explicit dual-layer organization."""

    USER = "user"
    MEMORY = "memory"


class WatermarkLevel(StrEnum):
    """Capacity watermark alert level for memory layers."""

    SAFE = "safe"
    WARNING = "warning"
    CRITICAL = "critical"
    OVERFLOW = "overflow"


class GarbageCategory(StrEnum):
    """Taxonomy of transient, low-value garbage blocked from long-term memory."""

    TASK_PROGRESS = "task_progress"
    EPHEMERAL_NUMBER = "ephemeral_number"
    TRANSIENT_ERROR = "transient_error"
    TRANSIENT_TEMPORAL = "transient_temporal"


@dataclass(frozen=True, slots=True)
class IntakeDecision:
    """Decision output produced by the MemoryIntakeGarbageFilter."""

    accepted: bool
    target_layer: MemoryLayerType | None
    rejected_reason: str | None = None
    garbage_category: GarbageCategory | None = None


@dataclass(frozen=True, slots=True)
class WatermarkStatus:
    """Capacity watermark evaluation output for a specific memory layer."""

    layer: MemoryLayerType
    current_chars: int
    max_chars: int
    usage_ratio: float
    level: WatermarkLevel
    warning_message: str | None = None
