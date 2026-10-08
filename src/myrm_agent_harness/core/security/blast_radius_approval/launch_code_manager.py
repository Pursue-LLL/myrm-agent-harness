"""
[POS] src/myrm_agent_harness/core/security/blast_radius_approval/launch_code_manager.py
[INPUT] time, secrets, typing, types
[OUTPUT] TypedLaunchCodeManager
Typed one-time challenge codes for high-risk irreversible actions.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import re
import secrets
import time

from .types import LaunchCodeRequirement

logger = logging.getLogger(__name__)

# Selected high-risk command patterns that mandate physical typed challenge codes
_HIGH_RISK_LAUNCH_CODE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bgit\s+push\s+(?:-[a-zA-Z]*f|--force)\b", re.IGNORECASE),
    re.compile(r"\brm\s+-[a-zA-Z]*r[a-zA-Z]*f\b", re.IGNORECASE),  # rm -rf, rm -fr, rm -r -f
    re.compile(r"\bvercel\s+--prod\b", re.IGNORECASE),
    re.compile(r"\b(DROP\s+DATABASE|DROP\s+TABLE|TRUNCATE\s+TABLE)\b", re.IGNORECASE),
)


class TypedLaunchCodeManager:
    """Manages single-use challenge tokens and keyword confirmations for high-risk commands."""

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self._ttl_seconds = ttl_seconds
        # Active challenge tickets indexed by token: token -> LaunchCodeRequirement
        self._active_tokens: dict[str, LaunchCodeRequirement] = {}

    def requires_launch_code(self, command: str) -> bool:
        """Check whether the given command mandates a typed confirmation challenge."""
        cmd = command.strip()
        return any(pat.search(cmd) is not None for pat in _HIGH_RISK_LAUNCH_CODE_PATTERNS)

    def generate_challenge(
        self,
        command: str,
        current_time: float | None = None,
    ) -> LaunchCodeRequirement:
        """Create a single-use 6-character typed challenge token for the command."""
        now = time.time() if current_time is None else current_time
        if not self.requires_launch_code(command):
            return LaunchCodeRequirement(requires_challenge=False)

        # Generate a distinct random 6-character uppercase token, e.g. "K9X4M2"
        token = "".join(secrets.choice("23456789ABCDEFGHJKLMNPQRSTUVWXYZ") for _ in range(6))
        expires_at = now + self._ttl_seconds

        req = LaunchCodeRequirement(
            requires_challenge=True,
            challenge_token=token,
            expected_keyword=token,
            expires_at=expires_at,
            is_used=False,
            prompt_message=f"High-risk command detected. Please type confirmation code '{token}' to authorize execution.",
        )
        self._active_tokens[token] = req
        logger.info("Issued launch challenge %s for high-risk command", token)
        return req

    def verify_and_consume(
        self,
        token: str,
        user_input: str,
        current_time: float | None = None,
    ) -> tuple[bool, str]:
        """Verify the typed launch code and immediately invalidate it (single-use semantics).

        Returns:
            A tuple of (is_valid, reason).
        """
        now = time.time() if current_time is None else current_time
        clean_token = token.strip()
        clean_input = user_input.strip()

        if clean_token not in self._active_tokens:
            return False, "Invalid or non-existent launch challenge token"

        ticket = self._active_tokens[clean_token]

        if ticket.is_used:
            return False, "Launch challenge token has already been consumed (replay blocked)"

        if ticket.expires_at is not None and now > ticket.expires_at:
            del self._active_tokens[clean_token]
            return False, "Launch challenge token has expired"

        if clean_input.upper() != (ticket.expected_keyword or "").upper():
            return False, f"Typed code mismatch: expected '{ticket.expected_keyword}'"

        # Consume ticket
        consumed_ticket = LaunchCodeRequirement(
            requires_challenge=ticket.requires_challenge,
            challenge_token=ticket.challenge_token,
            expected_keyword=ticket.expected_keyword,
            expires_at=ticket.expires_at,
            is_used=True,
            prompt_message=ticket.prompt_message,
        )
        self._active_tokens[clean_token] = consumed_ticket
        logger.info("Successfully verified and consumed launch challenge %s", clean_token)
        return True, "Launch challenge verified and consumed"
