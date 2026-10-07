"""Type definitions for full-spectrum in-process lifecycle interceptor and context pruning hub.

Defines fine-grained lifecycle event kinds, execution payloads, interceptor decisions,
and audit statistics for in-process agent lifecycle governance.

[INPUT]
- runtime.context.internal_external_message_pipeline_types::AgentMessage (POS: Type definitions for
  internal/external message separation and context transformation pipeline.)

[OUTPUT]
- LifecycleEventKind: Fine-grained classification of in-process agent runtime events.
- InterceptorAction: Decision made by an interceptor during event evaluation.
- LifecyclePayload: Immutable data transfer envelope for lifecycle events.
- InterceptorDecision: Outcome and audit record of an interceptor's evaluation.
- LifecycleHubMetrics: Execution counts and performance metrics of the interceptor hub.

[POS]
Type definitions for full-spectrum in-process lifecycle interceptor and context pruning hub.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum

from myrm_agent_harness.runtime.context.internal_external_message_pipeline_types import (
    AgentMessage,
)


class LifecycleEventKind(StrEnum):
    """Fine-grained classification of in-process agent runtime events."""

    INPUT = "input"
    BEFORE_TURN_START = "before_turn_start"
    TOOL_EXECUTION_START = "tool_execution_start"
    TOOL_EXECUTION_STREAM = "tool_execution_stream"
    TOOL_EXECUTION_END = "tool_execution_end"
    BASH_SPAWN_HOOK = "bash_spawn_hook"
    CONTEXT_DYNAMIC_PRUNE = "context_dynamic_prune"
    SESSION_BEFORE_COMPACT = "session_before_compact"
    TURN_END = "turn_end"


class InterceptorAction(StrEnum):
    """Decision made by an interceptor during event evaluation."""

    PROCEED = "proceed"
    MODIFY = "modify"
    BLOCK = "block"
    REPLACE = "replace"


@dataclass(frozen=True)
class LifecyclePayload:
    """Immutable data transfer envelope for lifecycle events."""

    event_kind: LifecycleEventKind
    session_id: str
    turn_index: int = 0
    timestamp: float = field(default_factory=time.time)
    text: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
    context_messages: list[AgentMessage] | None = None
    tool_name: str | None = None
    tool_args: dict[str, str] | None = None
    env_vars: dict[str, str] | None = None


@dataclass(frozen=True)
class InterceptorDecision:
    """Outcome and audit record of an interceptor's evaluation."""

    action: InterceptorAction
    modified_payload: LifecyclePayload | None = None
    block_reason: str | None = None
    interceptor_name: str = ""


@dataclass(frozen=True)
class LifecycleHubMetrics:
    """Execution counts and performance metrics of the interceptor hub."""

    dispatched_events_count: int
    blocked_events_count: int
    modified_events_count: int
    registered_interceptors_count: int
