"""Coding Agent Wave Preset Pipeline package (Item 45).

[INPUT]
- WaveStageEnum, WaveTaskNode, WavePresetConfig, CodingAgentWaveEngine.

[OUTPUT]
- Public exports for wave pipeline execution and strict stage gates.

[POS]
- myrm_agent_harness/agent/coordination/wave_orchestrator/__init__.py
"""

from __future__ import annotations

from .types import (
    WaveExecutionProgress,
    WavePresetConfig,
    WaveStageEnum,
    WaveTaskNode,
    WaveTaskStatusEnum,
)
from .wave_engine import (
    CodingAgentWaveEngine,
    CodingWaveError,
    CodingWaveGateError,
)

__all__ = [
    "CodingAgentWaveEngine",
    "CodingWaveError",
    "CodingWaveGateError",
    "WaveExecutionProgress",
    "WavePresetConfig",
    "WaveStageEnum",
    "WaveTaskNode",
    "WaveTaskStatusEnum",
]
