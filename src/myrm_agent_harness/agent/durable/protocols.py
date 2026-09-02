"""Durable Agent Harness core protocols and interface specifications.

[INPUT]
- .types::IntentRecord, TreeEntry, LaneState, OperationLogEntry, GlobalFactRecord, UsageRecord, ReplayDecision (POS: Typed data contracts)

[OUTPUT]
- DurableStorageProtocol: Interface for four-tier decoupled session persistence.
- EffectsBoundaryProtocol: Interface for intercepting and mocking external operations.
- MutationLineProtocol: Interface for single-writer serialized state mutation.
- ToolSafetyClassifierProtocol: Interface for checking tool execution idempotency and safety.

[POS]
Abstract protocol definitions for durable session storage, effects interception, and state machine mutation.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from myrm_agent_harness.agent.durable.types import (
    GlobalFactRecord,
    IntentRecord,
    LaneState,
    OperationLogEntry,
    ReplayDecision,
    TreeEntry,
    UsageRecord,
)


@runtime_checkable
class DurableStorageProtocol(Protocol):
    """Protocol for four-tier decoupled session storage."""

    async def append_tree_entry(self, entry: TreeEntry) -> None:
        """Append an immutable node to the conversation tree."""
        ...

    async def get_tree_entry(self, session_id: str, entry_id: str) -> TreeEntry | None:
        """Retrieve a specific tree entry by ID."""
        ...

    async def get_tree_history(self, session_id: str, leaf_id: str | None = None) -> list[TreeEntry]:
        """Retrieve the ordered branch history from root to the specified leaf."""
        ...

    async def get_or_create_lane(self, session_id: str, lane_id: str, parent_lane_id: str | None = None) -> LaneState:
        """Get or initialize a swimlane state."""
        ...

    async def update_lane_state(self, lane: LaneState) -> None:
        """Update current swimlane state and pointer."""
        ...

    async def append_intent(self, intent: IntentRecord) -> None:
        """Record an intent prior to producing a side effect."""
        ...

    async def update_intent(self, intent: IntentRecord) -> None:
        """Update an intent after producing a side effect."""
        ...

    async def get_intent(self, session_id: str, intent_id: str) -> IntentRecord | None:
        """Fetch intent by ID."""
        ...

    async def get_pending_intents(self, session_id: str, lane_id: str | None = None) -> list[IntentRecord]:
        """Fetch all uncompleted intents."""
        ...

    async def append_operation_log(self, op: OperationLogEntry) -> None:
        """Append an operational log entry."""
        ...

    async def get_operation_logs(self, session_id: str, lane_id: str | None = None) -> list[OperationLogEntry]:
        """Fetch operational log entries."""
        ...

    async def set_global_fact(self, session_id: str, key: str, value: Any) -> None:
        """Set a session-level global fact."""
        ...

    async def get_global_fact(self, session_id: str, key: str) -> Any | None:
        """Retrieve a global fact."""
        ...

    async def append_usage(self, usage: UsageRecord) -> None:
        """Append a monotonic token and cost record."""
        ...

    async def get_total_usage(self, session_id: str) -> list[UsageRecord]:
        """Fetch all usage records for a session."""
        ...


@runtime_checkable
class ToolSafetyClassifierProtocol(Protocol):
    """Protocol for determining tool replay safety level."""

    def classify_tool(self, tool_name: str, tool_args: dict[str, Any]) -> ReplayDecision:
        """Evaluate if a tool execution can be re-run or requires synthetic interrupted fallback."""
        ...


@runtime_checkable
class EffectsBoundaryProtocol(Protocol):
    """Protocol for intercepting, tracking, and mocking external effects in manual drive mode."""

    async def before_effect(self, intent: IntentRecord) -> None:
        """Hook called immediately before an external effect execution."""
        ...

    async def after_effect(self, intent: IntentRecord, result: Any) -> None:
        """Hook called immediately after an external effect execution."""
        ...
