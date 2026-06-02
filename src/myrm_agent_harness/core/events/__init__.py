"""Core event types — framework-agnostic event definitions.

Re-exports:
    AgentEventType: Event type enumeration for streaming responses.
    AgentStreamEvent: Strongly typed wrapper for agent stream events.
    THINKING_TAG_NAMES: Known thinking tag names for reasoning scrubber.
"""

from myrm_agent_harness.core.events.types import (
    AgentEventType,
    AgentStreamEvent,
    ApprovalInterceptedEventData,
    ContextBudgetSnapshot,
)

__all__ = [
    "THINKING_TAG_NAMES",
    "AgentEventType",
    "AgentStreamEvent",
    "ApprovalInterceptedEventData",
    "ContextBudgetSnapshot",
]

THINKING_TAG_NAMES: tuple[str, ...] = (
    "think",
    "thinking",
    "thought",
    "antthinking",
    "reasoning",
    "REASONING_SCRATCHPAD",
)
