"""Types and data contracts for dual-track session entry and operation branch projection.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- EntryKind: Category of domain fact entries stored in the session tree.
- OperationStatus: Lifecycle status of runtime operations.
- TokenUsage: Token consumption telemetry for a single execution step.
- SessionEntry: Immutable domain fact entry in the session tree topology.
- SessionOperation: Runtime operational telemetry record decoupled from LLM context.
- BranchSummary: Delta exploration summary between departed branch and LCA node.
- ProjectedContext: Dynamically projected working set context for an active branch.

[POS]
Types and data contracts for dual-track session tree and dynamic branch projection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class EntryKind(str, Enum):
    """Category of domain fact entries stored in the session tree."""

    MESSAGE = "message"
    MODEL_CHANGE = "model_change"
    THINKING_LEVEL = "thinking_level"
    ACTIVE_TOOLS = "active_tools"
    COMPACTION = "compaction"
    BRANCH_SUMMARY = "branch_summary"
    CUSTOM_FACT = "custom_fact"


class OperationStatus(str, Enum):
    """Lifecycle status of runtime operations."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Token consumption telemetry for a single execution step."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """Calculate total tokens consumed."""
        return self.input_tokens + self.output_tokens


@dataclass(frozen=True, slots=True)
class SessionEntry:
    """Immutable domain fact entry in the session tree topology.

    Represents 'what happened' in the domain conversation history.
    Each entry is linked via parent_id to form a DAG / tree structure.
    """

    entry_id: str
    parent_id: str | None
    session_id: str
    branch_id: str
    seq: int
    kind: EntryKind
    payload: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, str] = field(default_factory=dict)
    created_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass(frozen=True, slots=True)
class SessionOperation:
    """Runtime operational telemetry record decoupled from LLM context.

    Represents 'how the agent got here' during execution.
    Stored on an independent telemetry ledger to prevent context tax and inflation.
    """

    operation_id: str
    session_id: str
    branch_id: str
    step_name: str
    started_at_ms: int
    ended_at_ms: int
    duration_ms: int
    retry_count: int
    token_usage: TokenUsage
    status: OperationStatus
    entry_id: str | None = None
    tool_name: str | None = None
    queue_wait_ms: int = 0
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class BranchSummary:
    """Delta exploration summary between departed branch and LCA node.

    Captures intent, progress, key decisions, failures, and file manifests
    from the departed branch relative to the lowest common ancestor (LCA).
    """

    source_branch_id: str
    target_branch_id: str
    lca_entry_id: str
    departed_entry_ids: tuple[str, ...]
    read_files: tuple[str, ...]
    modified_files: tuple[str, ...]
    key_decisions: tuple[str, ...]
    blockers: tuple[str, ...]
    summary_text: str


@dataclass(frozen=True, slots=True)
class ProjectedContext:
    """Dynamically projected working set context for an active branch.

    Synthesized on-demand by traversing parent_id pointers from the active leaf
    node back to the session root, filtering out dead branches and applying
    effective configurations.
    """

    session_id: str
    branch_id: str
    leaf_entry_id: str
    lineage_entry_ids: tuple[str, ...]
    effective_model: str
    effective_thinking_level: str
    effective_active_tools: tuple[str, ...]
    projected_messages: tuple[dict[str, str], ...]
    total_projected_entries: int
