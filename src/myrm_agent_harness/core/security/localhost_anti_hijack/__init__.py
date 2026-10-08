"""Localhost anti-DNS-rebinding and origin anti-hijack guard suite."""

from __future__ import annotations

from .host_origin_guard import HostOriginGuard
from .setup_token_manager import SetupTokenManager
from .types import (
    HostOriginPolicy,
    SessionCookieSpec,
    SetupTokenRecord,
    SetupTokenStatus,
    ValidationResult,
    ValidationStatus,
)

__all__ = [
    "HostOriginGuard",
    "HostOriginPolicy",
    "SessionCookieSpec",
    "SetupTokenManager",
    "SetupTokenRecord",
    "SetupTokenStatus",
    "ValidationResult",
    "ValidationStatus",
]
