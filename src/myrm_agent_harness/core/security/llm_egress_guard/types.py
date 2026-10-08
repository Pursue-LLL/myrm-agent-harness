"""Domain types and models for LLM Egress Default-Deny & Credential Binding.

[INPUT]
- None.

[OUTPUT]
- Typed dataclasses and enums representing egress verdicts, domain allowlist rules,
  policy configurations, and evaluation results.

[POS]
- Harness core security domain models enforcing fail-closed LLM egress gating and
  strict destination-credential binding.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class LlmEgressVerdict(StrEnum):
    """Categorized decision from LLM egress evaluation."""

    PERMITTED = "PERMITTED"
    BLOCKED_NO_POLICY = "BLOCKED_NO_POLICY"
    BLOCKED_DOMAIN_NOT_ALLOWED = "BLOCKED_DOMAIN_NOT_ALLOWED"
    BLOCKED_CREDENTIAL_MISMATCH = "BLOCKED_CREDENTIAL_MISMATCH"
    BLOCKED_INVALID_TARGET = "BLOCKED_INVALID_TARGET"


@dataclass(frozen=True)
class DomainAllowlistRule:
    """Explicitly authorized egress destination and its bound credential identifiers."""

    rule_id: str
    domain_pattern: str
    bound_credential_ids: tuple[str, ...] = field(default_factory=tuple)
    description: str = ""
    require_credential_binding: bool = True


@dataclass(frozen=True)
class LlmEgressPolicy:
    """Egress policy configuration enforcing default-deny semantics."""

    policy_id: str
    allowed_rules: tuple[DomainAllowlistRule, ...]
    is_default_deny: bool = True
    enforced_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class LlmEgressEvaluationVerdict:
    """Outcome of pre-request egress inspection."""

    verdict: LlmEgressVerdict
    is_permitted: bool
    domain: str
    matched_rule_id: str | None
    bound_credential_id: str | None
    audit_id: str
    rationale: str


class LlmEgressDefaultDenyError(Exception):
    """Raised when an egress attempt is blocked due to default-deny policy enforcement."""


class LlmEgressCredentialBindingError(Exception):
    """Raised when a credential is sent to an unauthorized or mismatched endpoint."""
