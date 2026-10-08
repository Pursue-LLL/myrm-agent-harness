"""Data models for Triad Delegation Identity and Privilege Context.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- SubjectType: Classification of an identity subject in the delegation chain.
- SubjectIdentity: Immutable identity representation of an actor in the system.
- TriadDelegationToken: Cryptographic-grade immutable token representing the triad delegation contract.

[POS]
Immutable tokens capturing InitialRequester, ExecutorAgent, and BusinessApprover with strict
intersection-based privilege calculation to prevent amplification attacks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class SubjectType(StrEnum):
    """Classification of an identity subject in the delegation chain."""

    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class SubjectIdentity:
    """Immutable identity representation of an actor in the system."""

    subject_id: str
    subject_type: SubjectType
    display_name: str
    scopes: frozenset[str] = field(default_factory=frozenset)

    def to_dict(self) -> dict[str, object]:
        """Convert subject identity to serializable dictionary."""
        return {
            "subject_id": self.subject_id,
            "subject_type": self.subject_type.value,
            "display_name": self.display_name,
            "scopes": sorted(list(self.scopes)),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SubjectIdentity:
        """Construct subject identity from dictionary."""
        return cls(
            subject_id=str(data.get("subject_id", "")),
            subject_type=SubjectType(str(data.get("subject_type", SubjectType.HUMAN.value))),
            display_name=str(data.get("display_name", "")),
            scopes=frozenset(str(s) for s in data.get("scopes", ())),
        )


@dataclass(frozen=True, slots=True)
class TriadDelegationToken:
    """Cryptographic-grade immutable token representing the triad delegation contract.

    Invariants:
    1. Effective governed privilege = InitialRequester ∩ ExecutorAgent (+ BusinessApprover if present).
    2. Derived subagents automatically inherit the intersection of the parent's effective scopes
       and the subagent's allowed capabilities, strictly preventing privilege escalation.
    """

    initial_requester: SubjectIdentity
    executor_agent: SubjectIdentity
    business_approver: SubjectIdentity | None = None
    created_at: float = field(default_factory=time.time)
    token_ttl_seconds: float = 600.0

    @property
    def is_expired(self) -> bool:
        """Check if the delegation token has exceeded its validity window."""
        return (time.time() - self.created_at) > self.token_ttl_seconds

    @property
    def effective_scopes(self) -> frozenset[str]:
        """Compute the mathematically strict intersection of effective privileges."""
        # Baseline intersection between human sponsor and agent capability
        base_intersection = self.initial_requester.scopes & self.executor_agent.scopes

        # If an authorized business approver has endorsed the action, extend with approved scopes
        if self.business_approver is not None:
            return base_intersection | (self.business_approver.scopes & self.executor_agent.scopes)

        return base_intersection

    def has_scope(self, scope: str) -> bool:
        """Check if a specific governed scope is present in the effective scopes."""
        if self.is_expired:
            return False
        # Wildcard scope support
        if "*:*" in self.effective_scopes or "*" in self.effective_scopes:
            return True
        return scope in self.effective_scopes

    def derive_subagent_token(self, subagent: SubjectIdentity) -> TriadDelegationToken:
        """Derive a child delegation token for a subagent with intersection containment."""
        narrowed_scopes = self.effective_scopes & subagent.scopes
        narrowed_subagent = SubjectIdentity(
            subject_id=subagent.subject_id,
            subject_type=SubjectType.AGENT,
            display_name=subagent.display_name,
            scopes=narrowed_scopes,
        )
        return TriadDelegationToken(
            initial_requester=self.initial_requester,
            executor_agent=narrowed_subagent,
            business_approver=self.business_approver,
            created_at=self.created_at,
            token_ttl_seconds=self.token_ttl_seconds,
        )
