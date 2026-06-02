"""Three-layer error classification system for model fallback.

Provides structured error classification with recoverability and strategy mapping.

[INPUT]

[OUTPUT]
- RecoverabilityLevel: canrestorehierarchy
- FailoverReason: concreteerrortype
- ProbePolicy: probesstrategyconfiguration

[POS]
Three-layer error classification system. Layer 1: recoverability, Layer 2: concrete types, Layer 3: strategy mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RecoverabilityLevel(Enum):
    """Layer 1: Error recoverability classification.

    Determines whether an error is temporary or permanent.
    """

    TRANSIENT = "transient"  # Temporary errors (rate_limit, overloaded, timeout)
    SEMI_PERMANENT = (
        "semi_permanent"  # Semi-permanent errors (billing, session_expired)
    )
    PERMANENT = (
        "permanent"  # Permanent errors (auth_permanent, model_not_found, format)
    )


class FailoverReason(Enum):
    """Layer 2: Specific error type classification.

    Maps to specific error conditions from LLM providers.
    """

    # Transient errors
    RATE_LIMIT = "rate_limit"  # API rate limit exceeded
    OVERLOADED = "overloaded"  # Service overloaded/high demand
    TIMEOUT = "timeout"  # Network timeout or service unavailable
    THINKING_SIGNATURE = "thinking_signature"  # Anthropic thinking block signature invalid (retryable after strip)
    IMAGE_TOO_LARGE = (
        "image_too_large"  # Per-image size limit exceeded (retryable after shrink)
    )
    MEDIA_REJECTED = "media_rejected"  # Model does not support multimodal input (retryable after strip)
    UNKNOWN = "unknown"  # Unknown error (treat as transient)

    # Semi-permanent errors
    BILLING = "billing"  # Billing/payment issue
    SESSION_EXPIRED = "session_expired"  # Session or token expired

    # Permanent errors
    AUTH_PERMANENT = "auth_permanent"  # Permanent authentication failure
    MODEL_NOT_FOUND = "model_not_found"  # Model does not exist
    PROVIDER_POLICY_BLOCKED = (
        "provider_policy_blocked"  # Aggregator guardrail/data policy block
    )
    FORMAT_ERROR = "format"  # Invalid request format (our bug)
    RESPONSE_FORMAT_ERROR = (
        "response_format"  # LLM generated invalid JSON (model issue)
    )
    CONTEXT_OVERFLOW = "context_overflow"  # Context window exceeded (special case)
    LONG_CONTEXT_TIER = (
        "long_context_tier"  # Anthropic subscription tier gate (compress, don't retry)
    )
    SAFETY_BLOCK = "safety_block"  # Content blocked by safety/moderation filters

    @property
    def recoverability(self) -> RecoverabilityLevel:
        """Get recoverability level for this error type."""
        return _REASON_TO_RECOVERABILITY[self]

    @property
    def is_failoverable(self) -> bool:
        """Whether this error should trigger model fallback."""
        return self in _FAILOVERABLE_REASONS


@dataclass(frozen=True)
class ProbePolicy:
    """Layer 3: Probe strategy configuration.

    Defines how to probe a model during cooldown for this error type.

    Attributes:
        enabled: Whether probing is enabled for this error type
        interval_ms: Probe interval in milliseconds
        max_attempts: Maximum probe attempts during cooldown
        cooldown_ms: Cooldown duration in milliseconds
    """

    enabled: bool
    interval_ms: int
    max_attempts: int
    cooldown_ms: int


# ============================================================================
# Mapping: FailoverReason → RecoverabilityLevel
# ============================================================================

_REASON_TO_RECOVERABILITY: dict[FailoverReason, RecoverabilityLevel] = {
    # Transient
    FailoverReason.RATE_LIMIT: RecoverabilityLevel.TRANSIENT,
    FailoverReason.OVERLOADED: RecoverabilityLevel.TRANSIENT,
    FailoverReason.TIMEOUT: RecoverabilityLevel.TRANSIENT,
    FailoverReason.THINKING_SIGNATURE: RecoverabilityLevel.TRANSIENT,
    FailoverReason.IMAGE_TOO_LARGE: RecoverabilityLevel.TRANSIENT,
    FailoverReason.MEDIA_REJECTED: RecoverabilityLevel.TRANSIENT,
    FailoverReason.UNKNOWN: RecoverabilityLevel.TRANSIENT,
    # Semi-permanent
    FailoverReason.BILLING: RecoverabilityLevel.SEMI_PERMANENT,
    FailoverReason.SESSION_EXPIRED: RecoverabilityLevel.SEMI_PERMANENT,
    FailoverReason.RESPONSE_FORMAT_ERROR: RecoverabilityLevel.SEMI_PERMANENT,
    # Permanent
    FailoverReason.AUTH_PERMANENT: RecoverabilityLevel.PERMANENT,
    FailoverReason.MODEL_NOT_FOUND: RecoverabilityLevel.PERMANENT,
    FailoverReason.PROVIDER_POLICY_BLOCKED: RecoverabilityLevel.PERMANENT,
    FailoverReason.FORMAT_ERROR: RecoverabilityLevel.PERMANENT,
    FailoverReason.CONTEXT_OVERFLOW: RecoverabilityLevel.PERMANENT,
    FailoverReason.LONG_CONTEXT_TIER: RecoverabilityLevel.PERMANENT,
    FailoverReason.SAFETY_BLOCK: RecoverabilityLevel.PERMANENT,
}

# ============================================================================
# Mapping: FailoverReason → ProbePolicy
# ============================================================================

_REASON_TO_PROBE_POLICY: dict[FailoverReason, ProbePolicy] = {
    # Transient errors: Aggressive probing
    FailoverReason.RATE_LIMIT: ProbePolicy(
        enabled=True,
        interval_ms=60_000,  # 60s (matches typical API rate limit window)
        max_attempts=3,
        cooldown_ms=300_000,  # 5 minutes
    ),
    FailoverReason.OVERLOADED: ProbePolicy(
        enabled=True,
        interval_ms=15_000,  # 15s (services recover quickly)
        max_attempts=5,
        cooldown_ms=60_000,  # 1 minute
    ),
    FailoverReason.TIMEOUT: ProbePolicy(
        enabled=True,
        interval_ms=30_000,  # 30s (moderate recovery time)
        max_attempts=3,
        cooldown_ms=120_000,  # 2 minutes
    ),
    FailoverReason.UNKNOWN: ProbePolicy(
        enabled=True,
        interval_ms=30_000,  # 30s (default strategy)
        max_attempts=3,
        cooldown_ms=60_000,  # 1 minute
    ),
    # Semi-permanent errors: Conservative probing
    FailoverReason.BILLING: ProbePolicy(
        enabled=True,
        interval_ms=120_000,  # 120s (billing issues take time to resolve)
        max_attempts=2,
        cooldown_ms=600_000,  # 10 minutes
    ),
    FailoverReason.SESSION_EXPIRED: ProbePolicy(
        enabled=True,
        interval_ms=60_000,  # 60s (session refresh might happen)
        max_attempts=2,
        cooldown_ms=300_000,  # 5 minutes
    ),
    FailoverReason.RESPONSE_FORMAT_ERROR: ProbePolicy(
        enabled=True,
        interval_ms=30_000,  # 30s (model may self-correct on next attempt)
        max_attempts=2,
        cooldown_ms=120_000,  # 2 minutes
    ),
    # Transient with dedicated recovery (handled by StreamRecoveryMixin, not backoff)
    FailoverReason.THINKING_SIGNATURE: ProbePolicy(
        enabled=False,
        interval_ms=0,
        max_attempts=0,
        cooldown_ms=0,  # One-shot recovery via _handle_thinking_signature
    ),
    FailoverReason.IMAGE_TOO_LARGE: ProbePolicy(
        enabled=False,
        interval_ms=0,
        max_attempts=0,
        cooldown_ms=0,  # One-shot recovery via _handle_image_shrink
    ),
    FailoverReason.MEDIA_REJECTED: ProbePolicy(
        enabled=False,
        interval_ms=0,
        max_attempts=0,
        cooldown_ms=0,  # One-shot recovery via _handle_media_rejected
    ),
    # Permanent errors: No probing
    FailoverReason.AUTH_PERMANENT: ProbePolicy(
        enabled=False,
        interval_ms=0,
        max_attempts=0,
        cooldown_ms=float("inf"),  # Never recover
    ),
    FailoverReason.MODEL_NOT_FOUND: ProbePolicy(
        enabled=False,
        interval_ms=0,
        max_attempts=0,
        cooldown_ms=float("inf"),
    ),
    FailoverReason.PROVIDER_POLICY_BLOCKED: ProbePolicy(
        enabled=False,
        interval_ms=0,
        max_attempts=0,
        cooldown_ms=float("inf"),
    ),
    FailoverReason.FORMAT_ERROR: ProbePolicy(
        enabled=False,
        interval_ms=0,
        max_attempts=0,
        cooldown_ms=float("inf"),
    ),
    FailoverReason.CONTEXT_OVERFLOW: ProbePolicy(
        enabled=False,
        interval_ms=0,
        max_attempts=0,
        cooldown_ms=float("inf"),
    ),
    FailoverReason.LONG_CONTEXT_TIER: ProbePolicy(
        enabled=False,
        interval_ms=0,
        max_attempts=0,
        cooldown_ms=float("inf"),
    ),
    FailoverReason.SAFETY_BLOCK: ProbePolicy(
        enabled=False,
        interval_ms=0,
        max_attempts=0,
        cooldown_ms=float("inf"),
    ),
}

# ============================================================================
# Failoverable reasons
# ============================================================================

_FAILOVERABLE_REASONS = frozenset(
    {
        FailoverReason.RATE_LIMIT,
        FailoverReason.OVERLOADED,
        FailoverReason.TIMEOUT,
        FailoverReason.BILLING,
        FailoverReason.UNKNOWN,
        FailoverReason.RESPONSE_FORMAT_ERROR,
        FailoverReason.CONTEXT_OVERFLOW,
        FailoverReason.SAFETY_BLOCK,
    }
)


# ============================================================================
# Public API
# ============================================================================


def get_probe_policy(reason: FailoverReason) -> ProbePolicy:
    """Get probe policy for error type.

    Args:
        reason: Error type

    Returns:
        Probe policy configuration
    """
    return _REASON_TO_PROBE_POLICY[reason]


def should_allow_probe(reason: FailoverReason) -> bool:
    """Check if probing is allowed for error type.

    Args:
        reason: Error type

    Returns:
        True if probing is enabled
    """
    policy = get_probe_policy(reason)
    return policy.enabled
