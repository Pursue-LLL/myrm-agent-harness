"""Types and schemas for model switch subagent partitioning barrier and prefix protection.

[INPUT]
Primary session model locks, heterogeneous model invocation requests, and offload payloads.

[OUTPUT]
Type-safe barrier verdicts, isolated subagent dispatch contracts,
and compact cross-model handshake tags for prefix cache preservation.

[POS]
Item 123 in topic_06 roadmap: eliminates cross-model ping-pong cache eviction in primary sessions.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class OffloadReason(StrEnum):
    """Reason justifying offloading a request away from the primary model."""
    VISION_MULTIMODAL = "vision_multimodal"
    HEAVY_REASONING = "heavy_reasoning"
    CHEAP_SCREENING = "cheap_screening"
    RATE_LIMIT_ISOLATION = "rate_limit_isolation"


class BarrierRoutingAction(StrEnum):
    """Action dictated by the model switch partitioning barrier."""
    EXECUTE_ON_PRIMARY = "execute_on_primary"
    OFFLOAD_TO_ISOLATED_SUBAGENT = "offload_to_isolated_subagent"
    REJECT_MODEL_MUTATION = "reject_model_mutation"


@dataclass(frozen=True)
class PrimarySessionModelLock:
    """Immutable binding locking a primary chat session to a single LLM model."""
    session_id: str
    bound_model_id: str
    is_locked: bool = True
    locked_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class SubagentDispatchContract:
    """Specification of an isolated subagent execution partitioned away from primary session."""
    dispatch_id: str
    parent_session_id: str
    target_model_id: str
    offload_reason: OffloadReason
    isolated_instruction: str
    input_payload: str
    protected_primary_prefix_tokens: int
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class CompactCrossModelHandshake:
    """Structured append-only handshake envelope returned by isolated subagent to primary session."""
    dispatch_id: str
    target_model_id: str
    offload_reason: OffloadReason
    summary_result: str
    compact_tag: str
    tokens_saved_on_primary_prefix: int
    completed_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class BarrierInterceptionVerdict:
    """Outcome of inspecting an inbound LLM invocation against primary model lock."""
    action: BarrierRoutingAction
    session_id: str
    bound_model_id: str
    requested_model_id: str
    primary_cache_protected: bool
    dispatch_contract: SubagentDispatchContract | None = None
    reason: str = ""
