"""Admin authentication surface governance framework.

Provides unified management for password, email code, OAuth providers,
auto-registration switches, and anti-lockout safety invariants.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.admin_auth_surface.manager import (
    MASKED_SECRET_PLACEHOLDER,
    AdminAuthSurfaceManager,
)
from myrm_agent_harness.core.security.admin_auth_surface.types import (
    AdminAuthSurfaceConfig,
    AuthSurfaceValidationResult,
    LoginMethodSettings,
    OAuthConnectionConfig,
    OAuthProviderType,
)
from myrm_agent_harness.core.security.admin_auth_surface.validator import (
    AdminAuthSurfaceValidator,
)

__all__ = [
    "MASKED_SECRET_PLACEHOLDER",
    "AdminAuthSurfaceConfig",
    "AdminAuthSurfaceManager",
    "AdminAuthSurfaceValidator",
    "AuthSurfaceValidationResult",
    "LoginMethodSettings",
    "OAuthConnectionConfig",
    "OAuthProviderType",
]
