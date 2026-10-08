"""Domain types and models for Dual-Tier Root Admin & User API Key Isolation Suite.

[INPUT]
- None.

[OUTPUT]
- Typed dataclasses and enums representing key tiers, access planes, cross-tenant
  boundary checks, and dual-tier isolation verdicts.

[POS]
- Harness core security domain models ensuring strict physical separation between
  control-plane lifecycle operations and tenant data-plane memories.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class KeyTier(StrEnum):
    """Hierarchy tier of the API key."""

    ROOT_ADMIN = "ROOT_ADMIN"
    DERIVED_USER = "DERIVED_USER"


class AccessPlane(StrEnum):
    """Target operational plane for the requested operation."""

    CONTROL_PLANE = "CONTROL_PLANE"
    DATA_PLANE = "DATA_PLANE"


class IsolationVerdict(StrEnum):
    """Verdict evaluated by the dual-tier isolation gate."""

    PERMITTED = "PERMITTED"
    BLOCKED_DATA_PLANE_VIOLATION = "BLOCKED_DATA_PLANE_VIOLATION"
    BLOCKED_CONTROL_PLANE_VIOLATION = "BLOCKED_CONTROL_PLANE_VIOLATION"
    BLOCKED_CROSS_TENANT_BREACH = "BLOCKED_CROSS_TENANT_BREACH"
    BLOCKED_INVALID_KEY = "BLOCKED_INVALID_KEY"
    BLOCKED_REVOKED_KEY = "BLOCKED_REVOKED_KEY"


@dataclass(frozen=True)
class ApiKeyRecord:
    """Metadata describing a registered or derived API key."""

    key_id: str
    key_hash: str
    tier: KeyTier
    user_id: str | None = None
    agent_id: str | None = None
    tenant_id: str | None = None
    allowed_scopes: tuple[str, ...] = field(default_factory=tuple)
    is_revoked: bool = False
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class AccessEvaluationVerdict:
    """Outcome of access verification through dual-tier physical isolation gate."""

    verdict: IsolationVerdict
    is_permitted: bool
    effective_tier: KeyTier | None
    user_id: str | None
    tenant_id: str | None
    audit_id: str
    message: str
