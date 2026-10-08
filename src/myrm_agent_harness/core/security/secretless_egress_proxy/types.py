"""Type definitions for Secretless Credential Egress Proxy and Placeholder Swap Suite."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True, frozen=True)
class BoundCredentialSpec:
    """Credential specification bound exclusively to a target host domain."""

    target_host: str  # e.g. "api.github.com"
    auth_header_name: str  # e.g. "Authorization"
    auth_header_template: str  # e.g. "Bearer {secret}"
    real_secret: str
    placeholder: str  # e.g. "myrm_cred_a1b2c3d4"
    is_active: bool = True


@dataclass(slots=True, frozen=True)
class SwapEvent:
    """Audit log entry recorded whenever an egress request passes proxy."""

    timestamp: float
    target_host: str
    path: str
    method: str
    placeholder_used: str | None
    is_swapped: bool
    is_blocked: bool
    block_reason: str | None = None


@dataclass(slots=True, frozen=True)
class ProxyInspectionResult:
    """Outcome of inspecting outgoing request headers and resolving placeholder swap."""

    is_allowed: bool
    status_code: int
    headers_to_inject: dict[str, str] = field(default_factory=dict)
    reason: str = ""
    event: SwapEvent | None = None
