"""Type definitions for Redirect Private Address Hop Revalidation Suite.

[INPUT]
- stdlib dataclasses, enum

[OUTPUT]
- HopDisposition: enum of routing enforcement actions
- HopEvaluationResult: per-request hop evaluation outcome
- HopViolationAuditRecord: immutable audit record for security violations
- RedirectHopGuardConfig: configuration policy for hop-by-hop revalidation

[POS]
Core schema definitions for browser redirect hop revalidation.
Strictly avoids Any types; enforced under 400 lines limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class HopDisposition(StrEnum):
    """Routing enforcement actions taken on a network hop."""

    ALLOW = "ALLOW"
    ABORT_SUBRESOURCE = "ABORT_SUBRESOURCE"
    ABORT_AND_RESET_DOCUMENT = "ABORT_AND_RESET_DOCUMENT"


@dataclass(frozen=True, slots=True)
class HopEvaluationResult:
    """Outcome of inspecting an individual request or redirect hop."""

    disposition: HopDisposition
    is_private: bool
    matched_rule: str
    target_url: str
    resource_type: str
    reason: str


@dataclass(frozen=True, slots=True)
class HopViolationAuditRecord:
    """Immutable audit entry generated when a hop violates private network policy."""

    timestamp_iso: str
    initial_url: str
    hop_url: str
    resource_type: str
    disposition: HopDisposition
    matched_rule: str
    reason: str


@dataclass(frozen=True, slots=True)
class RedirectHopGuardConfig:
    """Configuration settings for redirect private address hop guard."""

    allow_private_networks: bool = False
    reset_to_about_blank: bool = True
    audit_history_max_size: int = 500
    custom_blocked_hostnames: tuple[str, ...] = field(
        default_factory=lambda: ("169.254.169.254", "instance-data", "metadata.google.internal")
    )
