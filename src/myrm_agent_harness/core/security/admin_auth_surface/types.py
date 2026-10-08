"""Domain models and types for Admin Authentication Surface management.

[INPUT]
- Typed data models representing authentication methods, OAuth connections,
  and anti-lockout security invariants.

[OUTPUT]
- Immutable dataclasses and enums for admin authentication surface configuration.

[POS]
- Core security primitive providing unified authentication governance across
  password, email code, OAuth providers, and auto-registration.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum


class OAuthProviderType(StrEnum):
    """Supported OAuth / OIDC identity providers."""

    GITHUB = "github"
    GOOGLE = "google"
    FEISHU = "feishu"
    GITLAB = "gitlab"
    OIDC_GENERIC = "oidc_generic"


@dataclass(frozen=True)
class LoginMethodSettings:
    """Settings controlling primary login methods."""

    password_enabled: bool = True
    email_code_enabled: bool = False
    email_code_auto_registration_enabled: bool = False


@dataclass(frozen=True)
class OAuthConnectionConfig:
    """Configuration for a third-party OAuth authentication provider."""

    id: str
    provider: OAuthProviderType
    name: str
    client_id: str
    client_secret: str
    authorize_url: str = ""
    token_url: str = ""
    scopes: Sequence[str] = field(default_factory=list)
    issuer_url: str | None = None
    enabled: bool = True
    auto_registration_enabled: bool = False


@dataclass(frozen=True)
class AdminAuthSurfaceConfig:
    """Unified security configuration for system authentication surface."""

    login_methods: LoginMethodSettings = field(default_factory=LoginMethodSettings)
    oauth_connections: Sequence[OAuthConnectionConfig] = field(default_factory=list)
    allow_public_registration: bool = False
    mfa_enforced: bool = False


@dataclass(frozen=True)
class AuthSurfaceValidationResult:
    """Outcome of validating authentication surface security invariants."""

    is_valid: bool
    active_login_method_count: int = 0
    errors: Sequence[str] = field(default_factory=list)
    warnings: Sequence[str] = field(default_factory=list)
