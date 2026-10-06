"""Type definitions for cross-session handoff contracts and continuity ledger.

Inspired by ai-memory handoff mechanisms. Provides structured contracts for
deterministic session handoffs, unconsumed workstream relay, and lifecycles.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class HandoffStatus(StrEnum):
    """Lifecycle status of a session handoff contract."""

    PENDING = "pending"
    CONSUMED = "consumed"
    ARCHIVED = "archived"
    EXPIRED = "expired"


class SessionLifecyclePhase(StrEnum):
    """Lifecycle phase of an agent session."""

    ACTIVE = "active"
    FINALIZING = "finalizing"
    FINALIZED = "finalized"
    ABANDONED = "abandoned"


class SynthesisMode(StrEnum):
    """Mode for synthesizing session handoff data."""

    DETERMINISTIC_RULE_ONLY = "deterministic_rule_only"
    HYBRID_AUGMENTED = "hybrid_augmented"


@dataclass(frozen=True)
class HandoffDecisionItem:
    """Architectural or implementation decision captured in a session."""

    decision_id: str
    topic: str
    rationale: str
    timestamp: float


@dataclass(frozen=True)
class HandoffTodoItem:
    """Pending or completed action item passed to future sessions."""

    task_id: str
    description: str
    priority: str = "P1"
    is_completed: bool = False


@dataclass(frozen=True)
class HandoffPitfallItem:
    """Pitfall, anti-pattern, or constraint discovered during execution."""

    warning_id: str
    context: str
    recommendation: str


@dataclass(frozen=True)
class CrossSessionHandoffContract:
    """Structured immutable handoff contract between sessions and agents."""

    handoff_id: str
    source_session_id: str
    created_at: float
    source_agent_profile: str
    target_task_summary: str
    decisions: list[HandoffDecisionItem] = field(default_factory=list)
    todos: list[HandoffTodoItem] = field(default_factory=list)
    pitfalls: list[HandoffPitfallItem] = field(default_factory=list)
    touched_files: list[str] = field(default_factory=list)
    executed_commands_summary: list[str] = field(default_factory=list)
    status: HandoffStatus = HandoffStatus.PENDING
    consumed_by_session_id: str | None = None
    consumed_at: float | None = None
    ttl_seconds: int = 86400 * 7  # 7 days default TTL


@dataclass(frozen=True)
class HandoffConsumptionReceipt:
    """Receipt proving safe atomic consumption of a handoff contract."""

    handoff_id: str
    consumer_session_id: str
    consumed_at: float
    active_todos_count: int
    injected_prompt_tokens_est: int
