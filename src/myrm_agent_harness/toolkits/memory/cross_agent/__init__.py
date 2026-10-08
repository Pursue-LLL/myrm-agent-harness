"""Cross-agent composable context isolation, divergence arbitration probe, and handoff integrity suite.

[INPUT]
- .arbitrator::MultiAgentConflictArbitrator
- .integrity::HandoffIntegrityPipeline
- .projector::ComposableContextProjector
- .tool::ArbitrateCrossAgentMemoryConflictInput, create_cross_agent_arbitration_tool
- .types::*

[OUTPUT]
- Public package interface for cross-agent memory management.

[POS]
Core module for multi-agent shared memory, context composition, and divergence settlement.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.cross_agent.arbitrator import (
    MultiAgentConflictArbitrator,
)
from myrm_agent_harness.toolkits.memory.cross_agent.integrity import (
    HandoffIntegrityPipeline,
)
from myrm_agent_harness.toolkits.memory.cross_agent.projector import (
    ComposableContextProjector,
)
from myrm_agent_harness.toolkits.memory.cross_agent.tool import (
    ArbitrateCrossAgentMemoryConflictInput,
    create_cross_agent_arbitration_tool,
)
from myrm_agent_harness.toolkits.memory.cross_agent.types import (
    AgentMemoryDivergence,
    ArbitrationOutcome,
    ComposableContextProjection,
    ConflictResolutionPolicy,
    ContextLayerKind,
    ContextProjectionLayer,
    HandoffPacket,
    HandoffVerificationResult,
    MemoryAssertion,
)

__all__ = [
    "AgentMemoryDivergence",
    "ArbitrateCrossAgentMemoryConflictInput",
    "ArbitrationOutcome",
    "ComposableContextProjection",
    "ComposableContextProjector",
    "ConflictResolutionPolicy",
    "ContextLayerKind",
    "ContextProjectionLayer",
    "HandoffIntegrityPipeline",
    "HandoffPacket",
    "HandoffVerificationResult",
    "MemoryAssertion",
    "MultiAgentConflictArbitrator",
    "create_cross_agent_arbitration_tool",
]
