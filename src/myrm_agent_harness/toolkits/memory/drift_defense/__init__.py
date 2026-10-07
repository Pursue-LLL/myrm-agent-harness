"""Public entry point for ground truth priority and code drift stale memory defense.

Provides pre-injection ground truth validation, sub-5ms physical presence
checks, and prompt-level stale memory decoration.
Strict typing applied: No `Any` types allowed.

[INPUT]
- toolkits.memory.drift_defense.decorator::StaleMemoryDecorator (POS: Prompt decorator and confidence decay
  applier for stale memories.)
- toolkits.memory.drift_defense.detector::GroundTruthDriftDetector (POS: High-performance pre-injection
  ground truth drift detector.)
- toolkits.memory.drift_defense.reference_extractor::ExtractedReference, GroundTruthReferenceExtractor (POS:
  Zero-LLM fast regular expression extractor for file paths and code symbols.)
- toolkits.memory.drift_defense.types::DriftCheckRequest, DriftCheckResult, DriftDefenseConfig, DriftType,
  MemoryDriftFinding (POS: Type definitions for ground truth priority and memory drift stale defense.)

[OUTPUT]
- Package facade re-exporting 9 public names: DriftCheckRequest, DriftCheckResult, DriftDefenseConfig,
  DriftType, ExtractedReference, GroundTruthDriftDetector, GroundTruthReferenceExtractor,
  MemoryDriftFinding, StaleMemoryDecorator

[POS]
Public entry point for ground truth priority and code drift stale memory defense.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.drift_defense.decorator import StaleMemoryDecorator
from myrm_agent_harness.toolkits.memory.drift_defense.detector import GroundTruthDriftDetector
from myrm_agent_harness.toolkits.memory.drift_defense.reference_extractor import (
    ExtractedReference,
    GroundTruthReferenceExtractor,
)
from myrm_agent_harness.toolkits.memory.drift_defense.types import (
    DriftCheckRequest,
    DriftCheckResult,
    DriftDefenseConfig,
    DriftType,
    MemoryDriftFinding,
)

__all__ = [
    "DriftCheckRequest",
    "DriftCheckResult",
    "DriftDefenseConfig",
    "DriftType",
    "ExtractedReference",
    "GroundTruthDriftDetector",
    "GroundTruthReferenceExtractor",
    "MemoryDriftFinding",
    "StaleMemoryDecorator",
]
