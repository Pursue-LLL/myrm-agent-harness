"""Rate Limit Data Types.

[INPUT]
- None

[OUTPUT]
- RateLimitBucket: Single rate limit bucket (e.g., RPM, TPM).
- RateLimitState: Full rate limit state for a provider/model.

[POS]
Data structures for proactive rate limit tracking.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass
class RateLimitBucket:
    """A single rate limit bucket (e.g., RPM, TPM)."""

    limit: int
    remaining: int
    reset_seconds: float
    updated_at: float

    @property
    def usage_pct(self) -> float:
        """Calculate usage percentage (0.0 to 1.0)."""
        if self.limit <= 0:
            return 0.0
        return max(0.0, min(1.0, (self.limit - self.remaining) / self.limit))

    @property
    def remaining_seconds_now(self) -> float:
        """Calculate remaining reset seconds from now."""
        elapsed = time.time() - self.updated_at
        return max(0.0, self.reset_seconds - elapsed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "remaining": self.remaining,
            "reset_seconds": self.reset_seconds,
            "updated_at": self.updated_at,
            "usage_pct": self.usage_pct,
            "remaining_seconds_now": self.remaining_seconds_now,
        }


@dataclass
class RateLimitState:
    """Full rate limit state for a provider/model."""

    provider: str
    model: str
    rpm: RateLimitBucket | None = None
    rph: RateLimitBucket | None = None
    tpm: RateLimitBucket | None = None
    tph: RateLimitBucket | None = None
    updated_at: float = 0.0

    @property
    def highest_usage_pct(self) -> float:
        """Get the highest usage percentage across all buckets."""
        pcts = [
            b.usage_pct
            for b in (self.rpm, self.rph, self.tpm, self.tph)
            if b is not None
        ]
        return max(pcts) if pcts else 0.0

    def can_consume(self, tokens: int, requests: int = 1) -> bool:
        """Check if there is enough quota to consume the given tokens/requests.

        Args:
            tokens: Estimated tokens to consume (input + output).
            requests: Number of requests to make.

        Returns:
            True if quota is sufficient, False otherwise.
        """
        # Check requests
        if (
            self.rpm
            and self.rpm.remaining < requests
            and self.rpm.remaining_seconds_now > 0
        ):
            return False
        if (
            self.rph
            and self.rph.remaining < requests
            and self.rph.remaining_seconds_now > 0
        ):
            return False

        # Check tokens
        if (
            self.tpm
            and self.tpm.remaining < tokens
            and self.tpm.remaining_seconds_now > 0
        ):
            return False
        return not (self.tph and self.tph.remaining < tokens and self.tph.remaining_seconds_now > 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "rpm": self.rpm.to_dict() if self.rpm else None,
            "rph": self.rph.to_dict() if self.rph else None,
            "tpm": self.tpm.to_dict() if self.tpm else None,
            "tph": self.tph.to_dict() if self.tph else None,
            "highest_usage_pct": self.highest_usage_pct,
            "updated_at": self.updated_at,
        }
