"""Domain contracts and types for nested approval restoration and compaction rollback.

[INPUT]
- None (Self-contained strongly-typed domain definitions).

[OUTPUT]
- ApprovalDecisionKind: Classification of approval outcome (approve, reject, pending).
- DecisionPrecedence: Resolution strategy between snapshot history and live environment.
- ApprovalDecisionRecord: Canonical record representing an approval grant or rejection.
- CompactionEntry: History entry unit subject to summarization replacement.
- CompactionRollbackBudget: Bounded allocation policy for compaction rollback buffer.
- NestedRestoreReceipt: Cryptographically verifiable audit receipt of restore execution.

[POS]
Domain contracts for nested approval restoration and bounded compaction rollback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import time
from typing import Mapping


class ApprovalDecisionKind(str, Enum):
    """Outcome state of an approval resolution."""

    APPROVE = "approve"
    REJECT = "reject"
    PENDING = "pending"


class DecisionPrecedence(str, Enum):
    """Precedence hierarchy resolving snapshot vs live decisions."""

    LIVE_PRIORITY = "live_priority"
    SNAPSHOT_ONLY = "snapshot_only"
    MERGE_SAVED = "merge_saved"


@dataclass(frozen=True)
class ApprovalDecisionRecord:
    """Canonical model capturing an approval decision with provenance and scope."""

    grant_id: str
    tool_name: str
    agent_owner: str
    decision: ApprovalDecisionKind
    is_permanent: bool = False
    message: str | None = None
    is_live: bool = False
    timestamp: float = field(default_factory=time.time)
    metadata: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)

    @property
    def scope_key(self) -> str:
        """Unique compound key binding a decision to a specific agent and tool."""
        return f"{self.agent_owner}::{self.tool_name}"

    def to_dict(self) -> dict[str, str | int | float | bool | None | dict[str, str | int | float | bool | None]]:
        """Serialize into normalized dictionary."""
        return {
            "grant_id": self.grant_id,
            "tool_name": self.tool_name,
            "agent_owner": self.agent_owner,
            "decision": self.decision.value,
            "is_permanent": self.is_permanent,
            "message": self.message,
            "is_live": self.is_live,
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CompactionEntry:
    """Historical turn or message entry subject to compaction replacement."""

    entry_id: str
    content: str
    token_count: int
    timestamp: float = field(default_factory=time.time)
    metadata: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, str | int | float | bool | None | dict[str, str | int | float | bool | None]]:
        return {
            "entry_id": self.entry_id,
            "content": self.content,
            "token_count": self.token_count,
            "timestamp": self.timestamp,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class CompactionRollbackBudget:
    """Configuration governing bounded rollback stash for compaction replacements."""

    max_rollback_entries: int = 50
    min_retained_turns: int = 2
    max_token_ceiling: int = 8192
    validation_enabled: bool = True

    def __post_init__(self) -> None:
        if self.max_rollback_entries <= 0:
            raise ValueError(f"max_rollback_entries must be positive, got {self.max_rollback_entries}")
        if self.min_retained_turns < 0:
            raise ValueError(f"min_retained_turns must be non-negative, got {self.min_retained_turns}")


@dataclass(frozen=True)
class NestedRestoreReceipt:
    """Verifiable audit receipt validating nested approval restore and compaction integrity."""

    receipt_id: str
    session_id: str
    restored_grants_count: int
    live_overrides_applied: int
    permanent_rejections_preserved: int
    rollback_budget_available: int
    compaction_validated: bool
    audit_checksum: str
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        *,
        receipt_id: str,
        session_id: str,
        restored_grants_count: int,
        live_overrides_applied: int,
        permanent_rejections_preserved: int,
        rollback_budget_available: int,
        compaction_validated: bool,
    ) -> NestedRestoreReceipt:
        payload = {
            "receipt_id": receipt_id,
            "session_id": session_id,
            "restored_grants_count": restored_grants_count,
            "live_overrides_applied": live_overrides_applied,
            "permanent_rejections_preserved": permanent_rejections_preserved,
            "rollback_budget_available": rollback_budget_available,
            "compaction_validated": compaction_validated,
        }
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        chk = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
        return cls(
            receipt_id=receipt_id,
            session_id=session_id,
            restored_grants_count=restored_grants_count,
            live_overrides_applied=live_overrides_applied,
            permanent_rejections_preserved=permanent_rejections_preserved,
            rollback_budget_available=rollback_budget_available,
            compaction_validated=compaction_validated,
            audit_checksum=chk,
        )
