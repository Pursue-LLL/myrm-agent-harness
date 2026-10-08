"""Desktop OAuth Browser Flow & RFC 8628 Device Code Grant Engine Suite.

[INPUT]
- PKCE generation, device flow coordination, silent token rotation.

[OUTPUT]
- Public exports of classes and utility functions for desktop and headless OAuth.

[POS]
- Harness core security package for zero-plaintext API key identity management.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.desktop_oauth_device.device_code_engine import (
    DeviceCodeEngine,
    generate_device_code,
    generate_user_code,
)
from myrm_agent_harness.core.security.desktop_oauth_device.pkce import (
    build_authorization_url,
    compute_code_challenge,
    generate_code_verifier,
    generate_pkce_challenge,
    verify_code_challenge,
)
from myrm_agent_harness.core.security.desktop_oauth_device.token_rotator import (
    RefreshHandler,
    SilentTokenRotator,
)
from myrm_agent_harness.core.security.desktop_oauth_device.types import (
    DesktopOAuthInitResponse,
    DeviceAuthStatus,
    DeviceCodeSession,
    OAuthPkceChallenge,
    OAuthProviderType,
    OAuthTokenGrant,
    TokenRotationResult,
    TokenStatus,
)

__all__ = [
    "DesktopOAuthInitResponse",
    "DeviceAuthStatus",
    "DeviceCodeEngine",
    "DeviceCodeSession",
    "OAuthPkceChallenge",
    "OAuthProviderType",
    "OAuthTokenGrant",
    "RefreshHandler",
    "SilentTokenRotator",
    "TokenRotationResult",
    "TokenStatus",
    "build_authorization_url",
    "compute_code_challenge",
    "generate_code_verifier",
    "generate_device_code",
    "generate_pkce_challenge",
    "generate_user_code",
    "verify_code_challenge",
]
