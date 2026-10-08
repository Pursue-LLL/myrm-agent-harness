# [INPUT] None (Domain foundational types for cryptographic sealed decision handoff)
# [OUTPUT] DecisionStatus, DecisionNode, NegativeInvariant, SealedReceipt, HandoffDecisionPackage, HandoffSanityReport, SealedDecisionError, SecretMaskingError, SealedDecisionVerificationError, DecisionGraphCycleError
# [POS] Domain data structures and error taxonomy for sealed decision handoff, secret masking, and invalidation graph

"""Domain types and error taxonomy for end-to-end sealed decision handoff."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from typing import Literal

DecisionStatus = Literal["ACTIVE", "REVOKED", "SUPERSEDED"]

DecisionValue = str | int | float | bool | list[str] | dict[str, str] | None
DecisionDict = dict[str, DecisionValue]

ReceiptValue = str | int | dict[str, str]
ReceiptDict = dict[str, ReceiptValue]


class SealedDecisionError(Exception):
    """Base error for sealed decision handoff and continuity."""


class SecretMaskingError(SealedDecisionError):
    """Raised when sensitive secret redaction or scoped pruning fails."""


class SealedDecisionVerificationError(SealedDecisionError):
    """Raised when cryptographic unsealing, auth tag, or SHA-256 digest fails."""


class DecisionGraphCycleError(SealedDecisionError):
    """Raised when an invalidation or supersedes cycle is detected in the graph."""


@dataclass(frozen=True)
class DecisionNode:
    """A single structured decision node capturing rationale, choices, and lifecycle status."""

    node_id: str
    title: str
    intent: str
    rationale: str
    chosen_option: str
    rejected_options: list[str] = field(default_factory=list)
    status: DecisionStatus = "ACTIVE"
    revoked_reason: str | None = None
    supersedes_id: str | None = None
    timestamp_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> DecisionDict:
        """Serialize node to a JSON-compatible dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: DecisionDict) -> DecisionNode:
        """Hydrate node from a dictionary."""
        return cls(
            node_id=str(data["node_id"]),
            title=str(data["title"]),
            intent=str(data["intent"]),
            rationale=str(data["rationale"]),
            chosen_option=str(data["chosen_option"]),
            rejected_options=[str(item) for item in data.get("rejected_options", [])],
            status=str(data.get("status", "ACTIVE")),  # type: ignore[arg-type]
            revoked_reason=data.get("revoked_reason"),
            supersedes_id=data.get("supersedes_id"),
            timestamp_iso=str(
                data.get(
                    "timestamp_iso",
                    datetime.now(timezone.utc).isoformat(),
                )
            ),
            metadata={str(k): str(v) for k, v in data.get("metadata", {}).items()},
        )


@dataclass(frozen=True)
class NegativeInvariant:
    """A negative behavioral guardrail derived from revoked or superseded choices."""

    rule: str
    context: str
    source_decision_id: str
    revocation_reason: str

    def to_dict(self) -> dict[str, str]:
        """Serialize negative invariant to dictionary."""
        return {
            "rule": self.rule,
            "context": self.context,
            "source_decision_id": self.source_decision_id,
            "revocation_reason": self.revocation_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> NegativeInvariant:
        """Hydrate invariant from dictionary."""
        return cls(
            rule=str(data["rule"]),
            context=str(data["context"]),
            source_decision_id=str(data["source_decision_id"]),
            revocation_reason=str(data.get("revocation_reason", "")),
        )


@dataclass(frozen=True)
class SealedReceipt:
    """Structured receipt contract referencing sealed ciphertext without exposing payload."""

    receipt_id: str
    topic: str
    enc: str
    key_ref: str
    sha256_digest: str
    summary: str
    payload_bytes_len: int
    created_at_iso: str
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> ReceiptDict:
        """Serialize receipt to dictionary."""
        return {
            "receipt_id": self.receipt_id,
            "topic": self.topic,
            "enc": self.enc,
            "key_ref": self.key_ref,
            "sha256_digest": self.sha256_digest,
            "summary": self.summary,
            "payload_bytes_len": self.payload_bytes_len,
            "created_at_iso": self.created_at_iso,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: ReceiptDict) -> SealedReceipt:
        """Hydrate receipt from dictionary."""
        return cls(
            receipt_id=str(data["receipt_id"]),
            topic=str(data["topic"]),
            enc=str(data["enc"]),
            key_ref=str(data["key_ref"]),
            sha256_digest=str(data["sha256_digest"]),
            summary=str(data["summary"]),
            payload_bytes_len=int(data["payload_bytes_len"]),
            created_at_iso=str(data["created_at_iso"]),
            metadata={str(k): str(v) for k, v in data.get("metadata", {}).items()},
        )


@dataclass(frozen=True)
class HandoffDecisionPackage:
    """The hydrated decision bundle handed off to the next agent or model."""

    topic: str
    active_decisions: list[DecisionNode]
    negative_invariants: list[NegativeInvariant]
    sanitized_env_vars: dict[str, str] = field(default_factory=dict)
    trace_artifacts: dict[str, str] = field(default_factory=dict)
    created_at_iso: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    metadata: dict[str, str] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize package to canonical JSON string."""
        raw = {
            "topic": self.topic,
            "active_decisions": [node.to_dict() for node in self.active_decisions],
            "negative_invariants": [inv.to_dict() for inv in self.negative_invariants],
            "sanitized_env_vars": self.sanitized_env_vars,
            "trace_artifacts": self.trace_artifacts,
            "created_at_iso": self.created_at_iso,
            "metadata": self.metadata,
        }
        return json.dumps(raw, ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, json_str: str) -> HandoffDecisionPackage:
        """Hydrate package from canonical JSON string."""
        raw = json.loads(json_str)
        return cls(
            topic=str(raw["topic"]),
            active_decisions=[
                DecisionNode.from_dict(item)
                for item in raw.get("active_decisions", [])
            ],
            negative_invariants=[
                NegativeInvariant.from_dict(item)
                for item in raw.get("negative_invariants", [])
            ],
            sanitized_env_vars={
                str(k): str(v) for k, v in raw.get("sanitized_env_vars", {}).items()
            },
            trace_artifacts={
                str(k): str(v) for k, v in raw.get("trace_artifacts", {}).items()
            },
            created_at_iso=str(raw.get("created_at_iso", "")),
            metadata={str(k): str(v) for k, v in raw.get("metadata", {}).items()},
        )


@dataclass(frozen=True)
class HandoffSanityReport:
    """Sanity verification report prior to or after decision handoff."""

    is_valid: bool
    active_count: int
    revoked_count: int
    superseded_count: int
    negative_invariants_count: int
    conflict_warnings: list[str] = field(default_factory=list)
