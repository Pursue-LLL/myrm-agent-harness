"""Idle and Budget Gated Auto-Memory Engine Suite (Item 123 P1).

Coordinates session idle detection, turn count and token budget gating,
and 6-dimensional structured memory artifact extraction.

[INPUT]
- Submodules: models, gate, extractor, engine.

[OUTPUT]
- Public package exports for automated session memory consolidation.

[POS]
Package facade for auto-memory suite.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.auto_memory.engine import (
    IdleAndBudgetGatedAutoMemoryEngine,
)
from myrm_agent_harness.toolkits.memory.auto_memory.extractor import (
    SixDimensionalExtractor,
)
from myrm_agent_harness.toolkits.memory.auto_memory.gate import (
    AutoMemoryGate,
)
from myrm_agent_harness.toolkits.memory.auto_memory.models import (
    AutoMemoryBudgetPolicy,
    AutoMemoryExtractionResult,
    AutoMemoryGatingDecision,
    SessionActivitySnapshot,
    SixDimensionalMemorySlice,
)

__all__ = [
    "AutoMemoryBudgetPolicy",
    "AutoMemoryExtractionResult",
    "AutoMemoryGate",
    "AutoMemoryGatingDecision",
    "IdleAndBudgetGatedAutoMemoryEngine",
    "SessionActivitySnapshot",
    "SixDimensionalExtractor",
    "SixDimensionalMemorySlice",
]
