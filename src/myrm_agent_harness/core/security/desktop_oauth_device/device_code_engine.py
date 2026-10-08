"""RFC 8628 Device Authorization Grant Engine for headless and sandbox environments.

[INPUT]
- Client IDs, verification URIs, polling intervals, and user authorization inputs.

[OUTPUT]
- DeviceCodeSession, polling evaluation states, and granted token exchanges.

[POS]
- Harness core security engine enabling zero-API-key logins via external browser/mobile.
"""

from __future__ import annotations

import secrets
import time
from typing import Final

from myrm_agent_harness.core.security.desktop_oauth_device.types import (
    DeviceAuthStatus,
    DeviceCodeSession,
    OAuthTokenGrant,
)

# RFC 8628 §6.1 recommended character set avoiding vowels and confusing glyphs (0, O, 1, I)
_BASE20_CHARSET: Final[str] = "BCDFGHJKLMNPQRSTVWXZ"


def generate_user_code() -> str:
    """Generate human-friendly 8-character user code formatted as XXXX-XXXX."""
    part1 = "".join(secrets.choice(_BASE20_CHARSET) for _ in range(4))
    part2 = "".join(secrets.choice(_BASE20_CHARSET) for _ in range(4))
    return f"{part1}-{part2}"


def generate_device_code() -> str:
    """Generate high-entropy cryptographically secure device code."""
    return secrets.token_urlsafe(32)


class DeviceCodeEngine:
    """Manages active RFC 8628 device authorization sessions and token exchange."""

    def __init__(self) -> None:
        self._sessions_by_device_code: dict[str, DeviceCodeSession] = {}
        self._device_code_by_user_code: dict[str, str] = {}
        self._last_poll_timestamps: dict[str, float] = {}

    def initiate_session(
        self,
        verification_uri: str,
        client_id: str,
        scope: str = "",
        expires_in: int = 600,
        interval: int = 5,
    ) -> DeviceCodeSession:
        """Create a new device authorization session."""
        device_code = generate_device_code()
        user_code = generate_user_code()

        delim = "&" if "?" in verification_uri else "?"
        verification_uri_complete = f"{verification_uri}{delim}user_code={user_code}"

        session = DeviceCodeSession(
            device_code=device_code,
            user_code=user_code,
            verification_uri=verification_uri,
            verification_uri_complete=verification_uri_complete,
            expires_in=expires_in,
            interval=interval,
            created_at=time.time(),
            status=DeviceAuthStatus.AUTHORIZATION_PENDING,
            granted_token=None,
        )

        self._sessions_by_device_code[device_code] = session
        self._device_code_by_user_code[user_code] = device_code
        return session

    def get_session_by_user_code(self, user_code: str) -> DeviceCodeSession | None:
        """Retrieve active session by user code, normalizing hyphens and casing."""
        normalized_code = user_code.strip().upper()
        device_code = self._device_code_by_user_code.get(normalized_code)
        if not device_code:
            return None
        return self._sessions_by_device_code.get(device_code)

    def authorize_user_code(
        self,
        user_code: str,
        token_grant: OAuthTokenGrant,
    ) -> tuple[bool, str]:
        """Authorize a pending device session using verified user code."""
        normalized_code = user_code.strip().upper()
        device_code = self._device_code_by_user_code.get(normalized_code)
        if not device_code:
            return False, f"Invalid or unknown user code: {user_code}"

        session = self._sessions_by_device_code.get(device_code)
        if not session:
            return False, "Session expired or not found"

        if session.is_expired():
            self._sessions_by_device_code[device_code] = DeviceCodeSession(
                device_code=session.device_code,
                user_code=session.user_code,
                verification_uri=session.verification_uri,
                verification_uri_complete=session.verification_uri_complete,
                expires_in=session.expires_in,
                interval=session.interval,
                created_at=session.created_at,
                status=DeviceAuthStatus.EXPIRED_TOKEN,
                granted_token=None,
            )
            return False, "Device authorization code has expired"

        # Mark as authorized with granted token
        self._sessions_by_device_code[device_code] = DeviceCodeSession(
            device_code=session.device_code,
            user_code=session.user_code,
            verification_uri=session.verification_uri,
            verification_uri_complete=session.verification_uri_complete,
            expires_in=session.expires_in,
            interval=session.interval,
            created_at=session.created_at,
            status=DeviceAuthStatus.AUTHORIZED,
            granted_token=token_grant,
        )
        return True, "Device code successfully authorized"

    def deny_user_code(self, user_code: str) -> tuple[bool, str]:
        """Explicitly deny authorization for a user code."""
        normalized_code = user_code.strip().upper()
        device_code = self._device_code_by_user_code.get(normalized_code)
        if not device_code:
            return False, f"Invalid or unknown user code: {user_code}"

        session = self._sessions_by_device_code.get(device_code)
        if not session:
            return False, "Session not found"

        self._sessions_by_device_code[device_code] = DeviceCodeSession(
            device_code=session.device_code,
            user_code=session.user_code,
            verification_uri=session.verification_uri,
            verification_uri_complete=session.verification_uri_complete,
            expires_in=session.expires_in,
            interval=session.interval,
            created_at=session.created_at,
            status=DeviceAuthStatus.ACCESS_DENIED,
            granted_token=None,
        )
        return True, "Authorization denied by user"

    def poll_session(
        self,
        device_code: str,
        enforce_interval: bool = True,
    ) -> tuple[DeviceAuthStatus, OAuthTokenGrant | None, str]:
        """Poll device authorization status conforming to RFC 8628 §3.5."""
        session = self._sessions_by_device_code.get(device_code)
        if not session:
            return DeviceAuthStatus.ACCESS_DENIED, None, "Unknown device code"

        now = time.time()

        # Check expiration
        if session.is_expired(now):
            return DeviceAuthStatus.EXPIRED_TOKEN, None, "Device authorization grant expired"

        # Rate limiting / slow down check
        last_poll = self._last_poll_timestamps.get(device_code, 0.0)
        self._last_poll_timestamps[device_code] = now
        if enforce_interval and last_poll > 0.0 and (now - last_poll) < session.interval:
            return DeviceAuthStatus.SLOW_DOWN, None, f"Polling too fast; wait at least {session.interval}s"

        if session.status == DeviceAuthStatus.AUTHORIZED:
            return DeviceAuthStatus.AUTHORIZED, session.granted_token, "Authorization granted"
        if session.status == DeviceAuthStatus.ACCESS_DENIED:
            return DeviceAuthStatus.ACCESS_DENIED, None, "User denied authorization request"

        return DeviceAuthStatus.AUTHORIZATION_PENDING, None, "Authorization pending user approval"
