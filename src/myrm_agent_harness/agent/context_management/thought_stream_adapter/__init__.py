"""Agent thought stream adapter and external client dual-mode event bridge package.

[INPUT]
- None (Package root exports).

[OUTPUT]
- AgentThoughtNormalizer: Formats structured headers, status summaries, and truncates tool payloads.
- AgentThoughtStreamAdapterAndExternalClientDualModeEventBridgeSuite: Full-name facade alias.
- AgentThoughtStreamAdapterSuite: Unified facade managing streaming lifecycles and dual-mode dispatch.
- ClientCapabilityNegotiator: Adaptive negotiation across user-agent, headers, and params.
- ClientReasoningMode: Target mode enum (REASONING_CONTENT, THINK_TAG_FALLBACK, SILENT).
- LongReasoningHeartbeatConduit: Manages activity timestamps and non-polluting keep-alive chunks.
- ThoughtActionType: Categorization of internal agent cognition actions.
- ThoughtAdapterConfig: Configuration parameters governing modes and keep-alive intervals.
- ThoughtStepDescriptor: Snapshot metadata and state of an agent execution step.
- ThoughtStreamChunk: Standardized event chunk ready for external SSE streaming.

[POS]
Package entry point for agent thought stream adaptation and external client bridge.
"""

from .agent_thought_normalizer import AgentThoughtNormalizer
from .agent_thought_stream_adapter_suite import (
    AgentThoughtStreamAdapterAndExternalClientDualModeEventBridgeSuite,
    AgentThoughtStreamAdapterSuite,
)
from .client_capability_negotiator import ClientCapabilityNegotiator
from .long_reasoning_heartbeat_conduit import LongReasoningHeartbeatConduit
from .thought_adapter_types import (
    ClientReasoningMode,
    ThoughtActionType,
    ThoughtAdapterConfig,
    ThoughtStepDescriptor,
    ThoughtStreamChunk,
)

__all__ = [
    "AgentThoughtNormalizer",
    "AgentThoughtStreamAdapterAndExternalClientDualModeEventBridgeSuite",
    "AgentThoughtStreamAdapterSuite",
    "ClientCapabilityNegotiator",
    "ClientReasoningMode",
    "LongReasoningHeartbeatConduit",
    "ThoughtActionType",
    "ThoughtAdapterConfig",
    "ThoughtStepDescriptor",
    "ThoughtStreamChunk",
]
