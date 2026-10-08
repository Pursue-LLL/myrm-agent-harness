"""Type definitions for localhost anti-DNS-rebinding and origin guard."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SetupTokenStatus = Literal["active", "consumed", "expired"]
ValidationStatus = Literal[
    "allowed",
    "rejected_host",
    "rejected_origin",
    "rejected_referer",
    "invalid_token",
]


@dataclass(slots=True, frozen=True)
class SetupTokenRecord:
    """One-time startup token generated when local agent starts."""

    token: str
    created_at: float
    expires_at: float
    is_consumed: bool = False
    consumed_at: float | None = None
    client_binding: str | None = None


@dataclass(slots=True, frozen=True)
class SessionCookieSpec:
    """HttpOnly session cookie specifications issued after token exchange."""

    cookie_name: str
    session_id: str
    max_age: int = 86400
    httponly: bool = True
    samesite: Literal["lax", "strict", "none"] = "strict"
    secure: bool = False
    path: str = "/"


@dataclass(slots=True, frozen=True)
class HostOriginPolicy:
    """Policy specification for allowed host names, ports, and origins."""

    allowed_hosts: tuple[str, ...] = ("127.0.0.1", "localhost", "::1", "[::1]")
    allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1",
        "http://localhost",
        "https://127.0.0.1",
        "https://localhost",
        "tauri://localhost",
        "http://tauri.localhost",
    )
    allow_null_origin: bool = False
    enforce_strict_mode: bool = True
    custom_ports: tuple[int, ...] = field(default_factory=tuple)


@dataclass(slots=True, frozen=True)
class ValidationResult:
    """Result of request host and origin security inspection."""

    is_allowed: bool
    status: ValidationStatus
    reason: str
    client_ip: str | None = None
    host_header: str | None = None
    origin_header: str | None = None
    referer_header: str | None = None
