"""Domain models for safe episodic memory forget operations.

[INPUT]
- Caller memory IDs, caller session IDs, forget scopes, and transaction events.

[OUTPUT]
- MemoryTier, ForgetScope, ForgetRequest, ParentProbeResult, SafeForgetResult, InvalidationEvent.

[POS]
- Core models and data structures for the safe episodic memory forget suite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class MemoryTier(str, Enum):
    """Memory storage tier classification."""

    EPISODIC = "episodic"
    WORKING = "working"
    SEMANTIC = "semantic"
    LEGACY = "legacy"


class ForgetScope(str, Enum):
    """Scope constraint for memory visibility and revocation."""

    SESSION = "session"
    GLOBAL = "global"


@dataclass(frozen=True)
class ForgetRequest:
    """Request specification for safe episodic forget execution."""

    memory_id: str
    caller_session_id: str
    user_id: str = ""
    allow_global: bool = True
    reason: str = ""


@dataclass(frozen=True)
class ParentProbeResult:
    """Result of probing competing parent rows across memory tiers."""

    memory_id: str
    authorized: bool
    episodic_exists: bool
    competing_tiers: tuple[MemoryTier, ...] = ()

    @property
    def has_competing_parents(self) -> bool:
        """Return True if another tier or legacy parent still claims this memory ID."""
        return len(self.competing_tiers) > 0


@dataclass(frozen=True)
class SafeForgetResult:
    """Outcome of a safe episodic forget invocation."""

    memory_id: str
    deleted: bool
    unauthorized: bool
    retained_shared_children: bool
    deleted_child_tables: tuple[str, ...] = ()
    message: str = ""


@dataclass(frozen=True)
class InvalidationEvent:
    """Event emitted when a memory is invalidated after commit."""

    event_name: str
    memory_id: str
    tier: str
    timestamp: float
    metadata: dict[str, str] = field(default_factory=dict)
