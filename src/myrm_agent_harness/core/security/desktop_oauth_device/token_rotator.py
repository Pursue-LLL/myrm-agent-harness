"""Silent Token Auto-Rotation and Lifecycle Management Engine.

[INPUT]
- OAuthTokenGrant records, provider identifiers, and token refresh callbacks.

[OUTPUT]
- TokenRotationResult detailing token validity, rotation status, and updated credentials.

[POS]
- Harness core security engine guaranteeing uninterrupted agent sessions via background token renewal.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from myrm_agent_harness.core.security.desktop_oauth_device.types import (
    OAuthTokenGrant,
    TokenRotationResult,
    TokenStatus,
)

RefreshHandler = Callable[[str, str], OAuthTokenGrant | None]


class SilentTokenRotator:
    """Manages proactive and transparent token rotation before expiration."""

    def __init__(self) -> None:
        self._grants: dict[str, OAuthTokenGrant] = {}

    def register_grant(self, provider: str, grant: OAuthTokenGrant) -> None:
        """Store or update active OAuth token grant for a provider."""
        self._grants[provider.lower()] = grant

    def get_grant(self, provider: str) -> OAuthTokenGrant | None:
        """Retrieve stored grant for a provider."""
        return self._grants.get(provider.lower())

    def remove_grant(self, provider: str) -> bool:
        """Revoke or remove stored grant."""
        return self._grants.pop(provider.lower(), None) is not None

    def check_status(
        self,
        provider: str,
        buffer_seconds: float = 60.0,
        current_time: float | None = None,
    ) -> TokenStatus:
        """Inspect the current validity status of a provider's token."""
        grant = self.get_grant(provider)
        if grant is None:
            return TokenStatus.REVOKED

        now = current_time if current_time is not None else time.time()
        if grant.is_expired(now):
            return TokenStatus.EXPIRED
        if grant.is_expiring_soon(buffer_seconds=buffer_seconds, current_time=now):
            return TokenStatus.EXPIRING_SOON

        return TokenStatus.ACTIVE

    def ensure_active_token(
        self,
        provider: str,
        refresh_handler: RefreshHandler | None = None,
        buffer_seconds: float = 60.0,
        current_time: float | None = None,
    ) -> TokenRotationResult:
        """Verify token freshness and execute silent rotation if approaching expiration."""
        norm_provider = provider.lower()
        grant = self.get_grant(norm_provider)
        if grant is None:
            return TokenRotationResult(
                status=TokenStatus.REVOKED,
                token=None,
                rotated=False,
                message=f"No token grant found for provider '{provider}'.",
            )

        now = current_time if current_time is not None else time.time()

        # Check if rotation is needed (either expired or expiring soon)
        needs_rotation = grant.is_expiring_soon(buffer_seconds=buffer_seconds, current_time=now)

        if not needs_rotation:
            return TokenRotationResult(
                status=TokenStatus.ACTIVE,
                token=grant,
                rotated=False,
                message="Token is valid and active.",
            )

        # Token needs rotation
        if not grant.refresh_token:
            status = TokenStatus.EXPIRED if grant.is_expired(now) else TokenStatus.EXPIRING_SOON
            return TokenRotationResult(
                status=status,
                token=grant,
                rotated=False,
                message="Token requires renewal but no refresh token is available.",
            )

        if refresh_handler is None:
            status = TokenStatus.EXPIRED if grant.is_expired(now) else TokenStatus.EXPIRING_SOON
            return TokenRotationResult(
                status=status,
                token=grant,
                rotated=False,
                message="Token requires renewal but no refresh handler callback provided.",
            )

        # Attempt silent refresh
        try:
            new_grant = refresh_handler(norm_provider, grant.refresh_token)
        except Exception as exc:
            status = TokenStatus.EXPIRED if grant.is_expired(now) else TokenStatus.EXPIRING_SOON
            return TokenRotationResult(
                status=status,
                token=grant,
                rotated=False,
                message=f"Token auto-rotation failed during handler invocation: {exc}",
            )

        if new_grant is None:
            status = TokenStatus.EXPIRED if grant.is_expired(now) else TokenStatus.EXPIRING_SOON
            return TokenRotationResult(
                status=status,
                token=grant,
                rotated=False,
                message="Refresh handler returned empty grant; token refresh rejected by provider.",
            )

        self.register_grant(norm_provider, new_grant)
        return TokenRotationResult(
            status=TokenStatus.ACTIVE,
            token=new_grant,
            rotated=True,
            message="Token silently rotated and refreshed successfully.",
        )
