# [POS]: myrm_agent_harness/toolkits/memory/drift_defense/__init__.py
# [INPUT]: None
# [OUTPUT]: GroundTruthDriftDetector, GroundTruthReferenceExtractor, StaleMemoryDecorator, Types
"""Public entry point for ground truth priority and code drift stale memory defense.

Provides pre-injection ground truth validation, sub-5ms physical presence
checks, and prompt-level stale memory decoration.
Strict typing applied: No `Any` types allowed.
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
