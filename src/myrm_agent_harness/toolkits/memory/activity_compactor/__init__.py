"""Hierarchical time-window activity compactor and telemetry pipeline toolkit.

[POS]
Harness framework layer toolkit providing ChatGPT Desktop Skysight-style 10min/6h/24h
hierarchical activity stream folding, milestone distillation, and telemetry (Topic 01 Item 87).
Strict typing applied: No `any` types allowed.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.activity_compactor.macro_distiller import (
    MacroMilestoneDistiller,
)
from myrm_agent_harness.toolkits.memory.activity_compactor.micro_folder import (
    MicroActivityFolder,
)
from myrm_agent_harness.toolkits.memory.activity_compactor.models import (
    ActivityActionType,
    CompactorPipelineConfig,
    CompactorPipelineTelemetry,
    DailyPreferenceArchive,
    MacroMilestoneFold,
    MicroActivitySlice,
    RawActivityEvent,
)
from myrm_agent_harness.toolkits.memory.activity_compactor.pipeline import (
    HierarchicalActivityCompactorPipeline,
)

__all__ = [
    "ActivityActionType",
    "RawActivityEvent",
    "MicroActivitySlice",
    "MacroMilestoneFold",
    "DailyPreferenceArchive",
    "CompactorPipelineTelemetry",
    "CompactorPipelineConfig",
    "MicroActivityFolder",
    "MacroMilestoneDistiller",
    "HierarchicalActivityCompactorPipeline",
]
