"""Types and schemas for session state diff delta protocol and explicit invalidation.

[INPUT]
Current runtime session variables (sandbox, approval, privileges, environment) and prior snapshots.

[OUTPUT]
Type-safe representations of state delta mutations, explicit invalidation notices,
and tail-appended injection payloads.

[POS]
Core protocol benchmarked against DeepSeek Harness 5-step cache protection and runtime state diffing.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class StateMutationKind(StrEnum):
    """Classification of state value change between conversational turns."""
    UNCHANGED = "unchanged"
    ADDED = "added"
    UPDATED = "updated"
    INVALIDATED = "invalidated"


@dataclass(frozen=True)
class StateDeltaItem:
    """Individual state variable mutation descriptor."""
    key: str
    mutation_kind: StateMutationKind
    old_value: str | None = None
    new_value: str | None = None
    invalidation_reason: str | None = None


@dataclass(frozen=True)
class SessionStateSnapshot:
    """Immutable point-in-time snapshot of active session runtime variables."""
    revision: int
    variables: Mapping[str, str]
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class SessionStateDeltaPackage:
    """Compiled delta package for tail-injection and prompt cache preservation."""
    from_revision: int
    to_revision: int
    has_mutations: bool
    mutations: tuple[StateDeltaItem, ...]
    formatted_tail_payload: str
    token_delta_estimate: int


@dataclass(frozen=True)
class StateDeltaAuditRecord:
    """Audit entry documenting state transitions and invalidation events."""
    audit_id: str
    turn_index: int
    from_revision: int
    to_revision: int
    mutations_count: int
    invalidated_keys: tuple[str, ...]
    applied_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
