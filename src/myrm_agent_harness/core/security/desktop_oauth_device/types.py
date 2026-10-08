"""Domain models and types for Desktop OAuth Browser Flow & RFC 8628 Device Code Grant.

[INPUT]
- None.

[OUTPUT]
- Typed dataclasses and enums representing PKCE challenges, desktop OAuth sessions,
  RFC 8628 device authorization flows, and silent token rotation lifecycle states.

[POS]
- Harness core security domain models for zero plaintext API key transmission.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class OAuthProviderType(StrEnum):
    """Supported external OAuth / Identity providers."""

    GITHUB = "github"
    GOOGLE = "google"
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    CUSTOM = "custom"


class DeviceAuthStatus(StrEnum):
    """RFC 8628 Device Authorization polling statuses."""

    AUTHORIZATION_PENDING = "authorization_pending"
    SLOW_DOWN = "slow_down"
    EXPIRED_TOKEN = "expired_token"
    ACCESS_DENIED = "access_denied"
    AUTHORIZED = "authorized"


class TokenStatus(StrEnum):
    """Token lifecycle status."""

    ACTIVE = "ACTIVE"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


@dataclass(frozen=True)
class OAuthPkceChallenge:
    """RFC 7636 Proof Key for Code Exchange challenge payload."""

    code_verifier: str
    code_challenge: str
    code_challenge_method: str = "S256"
    state: str = ""


@dataclass(frozen=True)
class DesktopOAuthInitResponse:
    """Desktop browser OAuth flow initialization response."""

    provider: str
    authorization_url: str
    state: str
    code_verifier: str
    loopback_port: int
    redirect_uri: str


@dataclass(frozen=True)
class OAuthTokenGrant:
    """OAuth token grant containing access and optional refresh tokens."""

    access_token: str
    refresh_token: str | None
    token_type: str = "Bearer"
    expires_in: int = 3600
    created_at: float = field(default_factory=time.time)
    scope: str = ""

    @property
    def expires_at(self) -> float:
        """Absolute epoch timestamp when the access token expires."""
        return self.created_at + self.expires_in

    def is_expired(self, current_time: float | None = None) -> bool:
        """Check if token is already expired."""
        now = current_time if current_time is not None else time.time()
        return now >= self.expires_at

    def is_expiring_soon(self, buffer_seconds: float = 60.0, current_time: float | None = None) -> bool:
        """Check if token will expire within the buffer threshold."""
        now = current_time if current_time is not None else time.time()
        return (self.expires_at - now) <= buffer_seconds


@dataclass(frozen=True)
class DeviceCodeSession:
    """RFC 8628 Device Authorization code session."""

    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int = 600
    interval: int = 5
    created_at: float = field(default_factory=time.time)
    status: DeviceAuthStatus = DeviceAuthStatus.AUTHORIZATION_PENDING
    granted_token: OAuthTokenGrant | None = None

    @property
    def expires_at(self) -> float:
        """Absolute epoch timestamp when the user code expires."""
        return self.created_at + self.expires_in

    def is_expired(self, current_time: float | None = None) -> bool:
        """Check if device session is expired."""
        now = current_time if current_time is not None else time.time()
        return now >= self.expires_at


@dataclass(frozen=True)
class TokenRotationResult:
    """Outcome of silent token rotation check or execution."""

    status: TokenStatus
    token: OAuthTokenGrant | None
    rotated: bool
    message: str
