"""Manager for one-time startup tokens and HttpOnly session cookies."""

from __future__ import annotations

import secrets
import time

from .types import SessionCookieSpec, SetupTokenRecord


class SetupTokenManager:
    """Manages high-entropy single-use setup tokens and session credentials.

    Prevents CSRF and unauthorized local access by requiring the first browser
    request to exchange a transient query token for a HttpOnly session cookie.
    """

    def __init__(
        self,
        cookie_name: str = "myrm_local_session",
        cookie_max_age: int = 86400,
        cookie_secure: bool = False,
    ) -> None:
        self._cookie_name: str = cookie_name
        self._cookie_max_age: int = cookie_max_age
        self._cookie_secure: bool = cookie_secure
        self._tokens: dict[str, SetupTokenRecord] = {}
        self._active_sessions: dict[str, float] = {}  # session_id -> expires_at

    def generate_token(
        self,
        ttl_seconds: int = 300,
        client_binding: str | None = None,
    ) -> SetupTokenRecord:
        """Generate a cryptographically secure one-time setup token."""
        token_str = secrets.token_urlsafe(32)
        now = time.time()
        record = SetupTokenRecord(
            token=token_str,
            created_at=now,
            expires_at=now + ttl_seconds,
            is_consumed=False,
            client_binding=client_binding,
        )
        self._tokens[token_str] = record
        return record

    def get_token_record(self, token: str) -> SetupTokenRecord | None:
        """Retrieve token record if it exists."""
        return self._tokens.get(token)

    def consume_token(
        self,
        token: str,
        client_binding: str | None = None,
    ) -> tuple[bool, str, SessionCookieSpec | None]:
        """Atomically consume the setup token and issue an HttpOnly session cookie.

        Returns:
            Tuple of (success, reason_or_message, session_cookie_spec).
        """
        record = self._tokens.get(token)
        if record is None:
            return False, "Token not found", None

        now = time.time()
        if record.is_consumed:
            return False, "Token has already been consumed", None

        if now > record.expires_at:
            return False, "Token has expired", None

        if (
            record.client_binding is not None
            and client_binding is not None
            and record.client_binding != client_binding
        ):
            return False, "Client binding mismatch", None

        # Mark consumed atomically
        consumed_record = SetupTokenRecord(
            token=record.token,
            created_at=record.created_at,
            expires_at=record.expires_at,
            is_consumed=True,
            consumed_at=now,
            client_binding=record.client_binding,
        )
        self._tokens[token] = consumed_record

        # Generate session
        session_id = secrets.token_hex(24)
        session_expires_at = now + self._cookie_max_age
        self._active_sessions[session_id] = session_expires_at

        spec = SessionCookieSpec(
            cookie_name=self._cookie_name,
            session_id=session_id,
            max_age=self._cookie_max_age,
            httponly=True,
            samesite="strict",
            secure=self._cookie_secure,
            path="/",
        )
        return True, "Token consumed successfully", spec

    def validate_session(self, session_id: str) -> bool:
        """Verify whether an active session cookie is valid and unexpired."""
        if not session_id:
            return False
        expires_at = self._active_sessions.get(session_id)
        if expires_at is None:
            return False
        if time.time() > expires_at:
            self._active_sessions.pop(session_id, None)
            return False
        return True

    def revoke_session(self, session_id: str) -> bool:
        """Revoke an active session."""
        if session_id in self._active_sessions:
            del self._active_sessions[session_id]
            return True
        return False

    def cleanup_expired(self) -> int:
        """Clean up expired tokens and sessions, returning count cleaned."""
        now = time.time()
        expired_tokens = [
            t for t, rec in self._tokens.items() if now > rec.expires_at
        ]
        for t in expired_tokens:
            del self._tokens[t]

        expired_sessions = [
            s for s, exp in self._active_sessions.items() if now > exp
        ]
        for s in expired_sessions:
            del self._active_sessions[s]

        return len(expired_tokens) + len(expired_sessions)
