"""Credential expiry checker for JWT/OAuth tokens.

Proactively detects expiring or expired credentials, enabling users to
refresh tokens before runtime failures.

[INPUT]
- pathlib::Path (stdlib: file operations)

[OUTPUT]
- CredentialExpiryChecker: checks JWT/OAuth token expiry
- ExpiryStatus: expiry status enum (valid, expiring_soon, expired, error)
- ExpiryResult: check result with status and details

[POS]
Optional enhancement for developer experience. Not required for core
functionality, but prevents common runtime failures due to expired tokens.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_EXPIRY_WARNING_DAYS = 7  # Warn if token expires within 7 days


class ExpiryStatus(StrEnum):
    """Credential expiry status."""

    VALID = "valid"
    """Token is valid and not expiring soon"""

    EXPIRING_SOON = "expiring_soon"
    """Token is expiring within warning threshold"""

    EXPIRED = "expired"
    """Token has already expired"""

    ERROR = "error"
    """Unable to determine expiry (parse error, missing fields, etc.)"""


@dataclass(frozen=True, slots=True)
class ExpiryResult:
    """Result of credential expiry check."""

    status: ExpiryStatus
    """Expiry status"""

    message: str
    """Human-readable message"""

    expires_at: datetime | None = None
    """Token expiration timestamp (if available)"""

    remaining_days: int | None = None
    """Days until expiry (if expiring soon or valid)"""


class CredentialExpiryChecker:
    """Checks JWT/OAuth token expiry with configurable warning threshold.

    Supports JWT tokens with 'exp' claim and Google OAuth tokens with
    'expiry' or 'token_expiry' fields.
    """

    def __init__(self, warning_days: int = _DEFAULT_EXPIRY_WARNING_DAYS) -> None:
        """Initialize checker.

        Args:
            warning_days: Warn if token expires within this many days (default 7)
        """
        self._warning_days = warning_days

    def check_credential_file(self, file_path: Path) -> ExpiryResult:
        """Check credential file for expiry.

        Automatically detects file type (JWT token, Google OAuth, etc.) and
        applies appropriate parsing logic.

        Args:
            file_path: Path to credential file

        Returns:
            ExpiryResult with expiry status and details
        """
        if not file_path.is_file():
            return ExpiryResult(
                status=ExpiryStatus.ERROR,
                message="file not found",
            )

        try:
            # Try JWT token first (most common)
            result = self._check_jwt_token(file_path)
            if result.status != ExpiryStatus.ERROR:
                return result

            # Try Google OAuth JSON format
            result = self._check_google_oauth_json(file_path)
            if result.status != ExpiryStatus.ERROR:
                return result

            # Unsupported format
            return ExpiryResult(
                status=ExpiryStatus.ERROR,
                message="unsupported credential format (not JWT or known OAuth format)",
            )

        except Exception as e:
            logger.debug("Error checking credential expiry for %s: %s", file_path, e)
            return ExpiryResult(
                status=ExpiryStatus.ERROR,
                message=f"parse error: {e}",
            )

    def _check_jwt_token(self, file_path: Path) -> ExpiryResult:
        """Check JWT token expiry (using 'exp' claim)."""
        try:
            # Lazy import to avoid hard dependency on PyJWT
            import jwt  # type: ignore[import-untyped]
        except (ImportError, TypeError):
            return ExpiryResult(
                status=ExpiryStatus.ERROR,
                message="PyJWT not installed (required for JWT expiry checks)",
            )

        try:
            with open(file_path) as f:
                token_content = f.read().strip()

            # Decode JWT without signature verification (we only need expiry)
            payload: dict[str, Any] = jwt.decode(
                token_content,
                options={"verify_signature": False},
            )

            exp_timestamp = payload.get("exp")
            if not exp_timestamp:
                # Not a JWT or missing 'exp' claim
                return ExpiryResult(
                    status=ExpiryStatus.ERROR,
                    message="not a JWT token (missing 'exp' claim)",
                )

            exp_dt = datetime.fromtimestamp(exp_timestamp)
            return self._evaluate_expiry(exp_dt)

        except (jwt.DecodeError, jwt.InvalidTokenError):
            # Not a valid JWT
            return ExpiryResult(
                status=ExpiryStatus.ERROR,
                message="not a valid JWT token",
            )
        except Exception as e:
            return ExpiryResult(
                status=ExpiryStatus.ERROR,
                message=f"JWT parse error: {e}",
            )

    def _check_google_oauth_json(self, file_path: Path) -> ExpiryResult:
        """Check Google OAuth JSON format (e.g. token.json from Google APIs)."""
        try:
            with open(file_path) as f:
                data: dict[str, Any] = json.load(f)

            # Google OAuth tokens typically have 'expiry' or 'token_expiry'
            expiry_str = data.get("expiry") or data.get("token_expiry")
            if not expiry_str:
                return ExpiryResult(
                    status=ExpiryStatus.ERROR,
                    message="not a Google OAuth token (missing 'expiry' field)",
                )

            # Parse ISO format or RFC 3339
            exp_dt = datetime.fromisoformat(expiry_str.replace("Z", "+00:00"))
            return self._evaluate_expiry(exp_dt.replace(tzinfo=None))  # Convert to naive

        except (json.JSONDecodeError, ValueError, KeyError) as e:
            return ExpiryResult(
                status=ExpiryStatus.ERROR,
                message=f"not a valid Google OAuth token: {e}",
            )

    def _evaluate_expiry(self, exp_dt: datetime) -> ExpiryResult:
        """Evaluate expiry timestamp and return result."""
        now = datetime.now()
        delta = exp_dt - now

        if delta.days < 0:
            # Expired
            return ExpiryResult(
                status=ExpiryStatus.EXPIRED,
                message=f"expired {abs(delta.days)} days ago",
                expires_at=exp_dt,
                remaining_days=delta.days,
            )

        if delta.days < self._warning_days:
            # Expiring soon
            return ExpiryResult(
                status=ExpiryStatus.EXPIRING_SOON,
                message=f"expires in {delta.days} days",
                expires_at=exp_dt,
                remaining_days=delta.days,
            )

        # Valid
        return ExpiryResult(
            status=ExpiryStatus.VALID,
            message=f"expires in {delta.days} days",
            expires_at=exp_dt,
            remaining_days=delta.days,
        )
