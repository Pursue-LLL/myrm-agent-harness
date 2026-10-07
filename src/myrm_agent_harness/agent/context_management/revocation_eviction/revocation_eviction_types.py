"""Strongly typed contracts for Context Sanitization and Memory Eviction Upon Revocation.

[INPUT]
- None (self-contained, standard library only).

[OUTPUT]
- RevocationScopeKind: Classification of access permission scopes being revoked.
- TaintedContentBlock: Lineage audit trace binding sensitive data blocks to revoked scopes.
- RevocationDirective: Instruction specifying the revoked scope and sanitization policy.
- SanitizationOutcome: Metrics and cleansed message payload after surgical context purging.

[POS]
Defines data structures powering lineage taint tracking, millisecond surgical
context sanitization, and working memory partition eviction.
"""

from __future__ import annotations

import enum
import time
from dataclasses import dataclass, field


class RevocationScopeKind(str, enum.Enum):
    """Classification of permission scopes eligible for dynamic revocation."""

    RESOURCE_ID = "resource_id"
    DATASOURCE = "datasource"
    TAG = "tag"
    PII_CATEGORY = "pii_category"


@dataclass(frozen=True, slots=True)
class TaintedContentBlock:
    """Lineage trace identifying a specific sensitive content block and its permission scope."""

    block_id: str
    turn_index: int
    scope_kind: RevocationScopeKind
    scope_id: str
    resource_name: str
    char_count: int
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True, slots=True)
class RevocationDirective:
    """Command triggering surgical purging of sensitive lineage and working memory."""

    revocation_id: str
    scope_id: str
    scope_kind: RevocationScopeKind = RevocationScopeKind.RESOURCE_ID
    reason: str = "Permission revoked by administrative governance."
    evict_working_memory: bool = True
    revoked_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class SanitizationOutcome:
    """Comprehensive diagnostic outcome of a surgical context sanitization cycle."""

    revocation_id: str
    scope_id: str
    sanitized_turns_count: int
    purged_blocks_count: int
    evicted_memory_entries_count: int
    cleansed_messages: list[dict[str, object]]
    audit_trail: list[str]
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, object]:
        """Serializes outcome metrics to dictionary."""
        return {
            "revocation_id": self.revocation_id,
            "scope_id": self.scope_id,
            "sanitized_turns_count": self.sanitized_turns_count,
            "purged_blocks_count": self.purged_blocks_count,
            "evicted_memory_entries_count": self.evicted_memory_entries_count,
            "audit_trail": list(self.audit_trail),
            "duration_ms": self.duration_ms,
        }
