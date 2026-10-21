"""Dual-Layer Profile & Working Notes Memory Budget & Garbage Purge Guard.

[INPUT]
- Candidate memory strings from user interactions or agent reflection
- types: MemoryLayerType, WatermarkLevel, GarbageCategory, IntakeDecision, WatermarkStatus

[OUTPUT]
- Public exports for MemoryIntakeGarbageFilter and CapacityWatermarkGovernor

[POS]
Harness toolkit memory subpackage providing Hermes-grade dual-layer memory
organization (USER <= 1375c, MEMORY <= 2200c) with deterministic garbage filtering.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.profile_notes.garbage_filter import (
    MemoryIntakeGarbageFilter,
)
from myrm_agent_harness.toolkits.memory.profile_notes.intake_gate import (
    check_memory_not_garbage,
    filter_intake_garbage,
    format_profile_notes_prompt_section,
)
from myrm_agent_harness.toolkits.memory.profile_notes.types import (
    GarbageCategory,
    IntakeDecision,
    MemoryLayerType,
    WatermarkLevel,
    WatermarkStatus,
)
from myrm_agent_harness.toolkits.memory.profile_notes.watermark_governor import (
    DEFAULT_MEMORY_MAX_CHARS,
    DEFAULT_USER_MAX_CHARS,
    CapacityWatermarkGovernor,
)

__all__ = [
    "CapacityWatermarkGovernor",
    "DEFAULT_MEMORY_MAX_CHARS",
    "DEFAULT_USER_MAX_CHARS",
    "GarbageCategory",
    "IntakeDecision",
    "MemoryIntakeGarbageFilter",
    "MemoryLayerType",
    "WatermarkLevel",
    "WatermarkStatus",
    "check_memory_not_garbage",
    "filter_intake_garbage",
    "format_profile_notes_prompt_section",
]
