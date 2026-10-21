"""Strongly typed data contracts for loopback proxy bypass and self-healing.

[OUTPUT]
- HealthStatus: State of loopback connection health.
- ProxySoftwareKind: Known proxy software types (Surge, Clash, Clash Verge, Generic).
- ProxyEnvironmentSnapshot: Snapshot of active system proxy environment variables.
- LoopbackProbeResult: Outcome of an active loopback connection probe.
- ProxyRemediationRule: Actionable bypass rule for operator configuration files.

[INPUT]
- __future__
- time
- dataclasses
- enum

[OUTPUT]
- HealthStatus
- ProxySoftwareKind
- ProxyEnvironmentSnapshot
- LoopbackProbeResult
- ProxyRemediationRule

[POS]
Strongly typed data contracts for loopback proxy bypass and self-healing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class HealthStatus(StrEnum):
    """Health classification of local loopback endpoints."""

    HEALTHY = "healthy"
    INTERCEPTED = "intercepted"
    UNREACHABLE = "unreachable"
    HEALED = "healed"


class ProxySoftwareKind(StrEnum):
    """Known local system proxy software."""

    SURGE = "surge"
    CLASH = "clash"
    CLASH_VERGE = "clash_verge"
    GENERIC = "generic"


@dataclass(frozen=True)
class ProxyEnvironmentSnapshot:
    """Captured snapshot of system proxy environment variables."""

    http_proxy: str | None = None
    https_proxy: str | None = None
    all_proxy: str | None = None
    no_proxy: str | None = None
    captured_at: float = field(default_factory=time.time)

    @property
    def has_any_proxy_configured(self) -> bool:
        """Return True if any upstream proxy variable is defined."""
        return bool(self.http_proxy or self.https_proxy or self.all_proxy)

    @property
    def covers_standard_loopback(self) -> bool:
        """Check if NO_PROXY adequately includes standard loopback addresses."""
        if not self.no_proxy:
            return False
        tokens = {t.strip().lower() for t in self.no_proxy.split(",") if t.strip()}
        return {"127.0.0.1", "localhost"}.issubset(tokens)


@dataclass(frozen=True)
class LoopbackProbeResult:
    """Detailed diagnostic outcome of probing a local loopback target."""

    target_host: str
    target_port: int
    status: HealthStatus
    is_reachable: bool
    latency_ms: float = 0.0
    intercepted_by_proxy: bool = False
    detected_proxy_signature: str | None = None
    error_message: str | None = None
    timestamp: float = field(default_factory=time.time)


@dataclass(frozen=True)
class ProxyRemediationRule:
    """Operator configuration snippet to unblock loopback traffic."""

    software: ProxySoftwareKind
    rule_directive: str
    target_config_section: str
    human_explanation: str
