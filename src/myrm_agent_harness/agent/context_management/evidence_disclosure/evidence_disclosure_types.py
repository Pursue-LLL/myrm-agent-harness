"""Domain contracts for active and completed isomorphic evidence disclosure.

[INPUT]
- None (Self-contained strongly-typed definitions).

[OUTPUT]
- EvidenceSourceState: State discriminator distinguishing active turns from completed history.
- EvidenceOutcome: Standard outcome state for tool/action execution.
- QueryScopeKind: Deterministic scope constraint for evidence queries.
- ActionExecutionFailure: Detailed payload for failed action execution.
- ActionDetailDescriptor: Canonical isomorphic descriptor shared between active and history.
- EvidenceRefTarget: Structured reference representation of a collection or leaf action.
- RealReadSlice: Content slice bound to deterministic real-reading offsets and checksum.
- PaginatedEvidencePage: Container with real-read window pagination metadata.
- EvidenceDisclosureReceipt: Attestation receipt confirming evidence disclosure parity.

[POS]
Domain contracts for unified action evidence disclosure and deterministic query scopes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
import time
from typing import Mapping, Sequence


class EvidenceSourceState(str, Enum):
    """Source lifecycle state of the evidenced action."""

    ACTIVE_TURN = "active_turn"
    COMPLETED_HISTORY = "completed_history"


class EvidenceOutcome(str, Enum):
    """Execution outcome status of an action."""

    SUCCESS = "success"
    FAILURE = "failure"
    RUNNING = "running"
    SETTLED = "settled"


class QueryScopeKind(str, Enum):
    """Deterministic scope boundary for query isolation."""

    ACTIVE_TURN = "active_turn"
    COMPLETED_HISTORY = "completed_history"
    UNIFIED_ALL = "unified_all"


@dataclass(frozen=True)
class ActionExecutionFailure:
    """Detailed error record when an action execution fails."""

    code: str
    message: str
    details: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, str | dict[str, str]]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class EvidenceRefTarget:
    """Parsed structured representation of an evidence action ref."""

    turn_ref: str
    occurrence: int | None = None
    is_collection: bool = False

    @property
    def canonical_ref(self) -> str:
        if self.is_collection:
            return f"{self.turn_ref}#actions"
        if self.occurrence is not None:
            return f"{self.turn_ref}#action/{self.occurrence}"
        return self.turn_ref


@dataclass(frozen=True)
class ActionDetailDescriptor:
    """Canonical Action detail shared between active evidence and completed history."""

    turn_ref: str
    occurrence: int
    action_name: str
    request: Mapping[str, str | int | float | bool | None]
    outcome: EvidenceOutcome
    source_state: EvidenceSourceState
    result: Mapping[str, str | int | float | bool | None] | str | None = None
    failure: ActionExecutionFailure | None = None
    references: tuple[str, ...] = ()
    timestamp: float = field(default_factory=time.time)
    kind: str = "session_action"

    @property
    def ref(self) -> str:
        return f"{self.turn_ref}#action/{self.occurrence}"

    @property
    def content_hash(self) -> str:
        """Deterministic SHA-256 fingerprint of the normalized action payload."""
        payload = {
            "kind": self.kind,
            "ref": self.ref,
            "turn_ref": self.turn_ref,
            "occurrence": self.occurrence,
            "action_name": self.action_name,
            "request": dict(self.request),
            "outcome": self.outcome.value,
            "result": dict(self.result) if isinstance(self.result, dict) else self.result,
            "failure": self.failure.to_dict() if self.failure else None,
            "references": list(self.references),
        }
        normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def to_projection(self) -> dict[str, str | int | float | bool | None | list[str] | dict[str, str | int | float | bool | None]]:
        """Canonical dictionary projection shared across active evidence and completed history."""
        proj: dict[str, str | int | float | bool | None | list[str] | dict[str, str | int | float | bool | None]] = {
            "kind": self.kind,
            "ref": self.ref,
            "turn_ref": self.turn_ref,
            "occurrence": self.occurrence,
            "action": self.action_name,
            "request": dict(self.request),
            "outcome": self.outcome.value,
            "source_state": self.source_state.value,
            "content_hash": self.content_hash,
            "timestamp": self.timestamp,
        }
        if self.result is not None:
            proj["result"] = dict(self.result) if isinstance(self.result, dict) else self.result
        if self.failure is not None:
            proj["failure"] = self.failure.to_dict()
        if self.references:
            proj["references"] = list(self.references)
        return proj


@dataclass(frozen=True)
class RealReadSlice:
    """Deterministic excerpt bound to real text reading offsets and checksum."""

    unit_id: str
    start_offset: int
    end_offset: int
    actual_text: str
    content_sha256: str
    total_unit_length: int


@dataclass(frozen=True)
class PaginatedEvidencePage:
    """Paginated collection of evidence descriptors coupled with real-read slices."""

    page_number: int
    page_size: int
    total_records: int
    total_pages: int
    items: tuple[ActionDetailDescriptor, ...]
    slices: tuple[RealReadSlice, ...]
    has_next: bool
    has_previous: bool


@dataclass(frozen=True)
class EvidenceDisclosureReceipt:
    """Attestation receipt proving that evidence disclosure conformed to isomorphic parity."""

    receipt_id: str
    action_ref: str
    isomorphic_parity: bool
    source_state: EvidenceSourceState
    fingerprint: str
    timestamp: float = field(default_factory=time.time)
