"""Types and data structures for Muse-Style Secure VM Isolation and Sentinel Suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


def _utc_now() -> datetime:
    """Return current UTC timestamp."""
    return datetime.now(UTC)


class SandboxIsolationTier(StrEnum):
    """Isolation tiers for user-dedicated execution environments."""

    DEDICATED_SECURE_VM = "dedicated_secure_vm"
    CONTAINER_NAMESPACE = "container_namespace"
    LOCAL_RESTRICTED = "local_restricted"


class SentinelVerdict(StrEnum):
    """Decision produced by the pre-outbound Sentinel review watchdog."""

    ALLOW = "allow"
    BLOCK = "block"
    REQUIRE_CHALLENGE = "require_challenge"


class TokenType(StrEnum):
    """Single-use ephemeral token classification."""

    VIRTUAL_PAYMENT_CARD = "virtual_payment_card"
    EPHEMERAL_BEARER_TOKEN = "ephemeral_bearer_token"
    SINGLE_USE_API_KEY = "single_use_api_key"


@dataclass(frozen=True, slots=True)
class SecureVmProfile:
    """User-dedicated secure container/VM environment descriptor."""

    vm_id: str
    user_id: str
    isolation_tier: SandboxIsolationTier
    volume_mount: str
    egress_mode: str = "sentinel_proxy"
    credential_sealed: bool = True
    created_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, slots=True)
class OutboundTrafficPayload:
    """Outbound request frame submitted to Sentinel for pre-flight evaluation."""

    request_id: str
    destination_url: str
    method: str
    headers: dict[str, str]
    body_preview: str
    source_vm_id: str


@dataclass(frozen=True, slots=True)
class SentinelReviewResult:
    """Outcome of pre-outbound inspection performed by Sentinel."""

    request_id: str
    verdict: SentinelVerdict
    matched_rule: str | None
    reason: str
    risk_score: float
    timestamp: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, slots=True)
class SingleUseToken:
    """Ephemeral, single-use credential or virtual payment token."""

    token_id: str
    virtual_token: str
    token_type: TokenType
    max_amount: float
    currency: str
    bound_recipient: str
    is_consumed: bool
    expires_at: datetime
    created_at: datetime = field(default_factory=_utc_now)


@dataclass(frozen=True, slots=True)
class TokenRedemptionResult:
    """Result of attempting to redeem a single-use credential."""

    token_id: str
    success: bool
    reason: str
    timestamp: datetime = field(default_factory=_utc_now)
