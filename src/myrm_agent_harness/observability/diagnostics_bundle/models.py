"""
[INPUT]: Diagnostic events, sandbox health metrics, and client context data.
[OUTPUT]: Strongly-typed diagnostic bundle structures for incident triage and ticketing.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/diagnostics_bundle/models.py
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class DiagnosticLogEvent:
    """Represents a structured log entry captured before or during an incident."""

    timestamp: str
    level: str  # e.g., "INFO", "WARN", "ERROR", "CRITICAL"
    subsystem: str  # e.g., "sandbox_kernel", "network_proxy", "llm_client"
    message: str
    metadata: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "subsystem": self.subsystem,
            "message": self.message,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SandboxVitals:
    """Snapshot of real-time sandbox runtime metrics."""

    cpu_pct: float
    mem_pct: float
    disk_free_bytes: int
    network_state: str  # e.g., "healthy", "degraded", "disconnected"
    uptime_secs: float
    is_volume_healthy: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "cpu_pct": round(self.cpu_pct, 2),
            "mem_pct": round(self.mem_pct, 2),
            "disk_free_bytes": self.disk_free_bytes,
            "network_state": self.network_state,
            "uptime_secs": round(self.uptime_secs, 2),
            "is_volume_healthy": self.is_volume_healthy,
        }


@dataclass(frozen=True)
class ClientContext:
    """Snapshot of frontend or client execution state."""

    client_version: str
    platform: str  # e.g., "darwin", "linux", "win32", "web"
    browser_or_os: str
    active_route: str
    session_id: str

    def to_dict(self) -> dict[str, object]:
        return {
            "client_version": self.client_version,
            "platform": self.platform,
            "browser_or_os": self.browser_or_os,
            "active_route": self.active_route,
            "session_id": self.session_id,
        }


@dataclass
class EncryptedDiagnosticBundle:
    """
    Immutable, integrity-verified diagnostic snapshot bundle.
    Contains scrubbed logs, vitals, and client metadata with HMAC checksum.
    """

    bundle_id: str
    session_id: str
    sandbox_id: str
    vitals: SandboxVitals
    logs: list[DiagnosticLogEvent]
    client_context: ClientContext
    scrubbed_pii_count: int
    checksum: str
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def canonical_bytes(self) -> bytes:
        """Produces canonical JSON serialization bytes for checksum verification."""
        data = {
            "bundle_id": self.bundle_id,
            "session_id": self.session_id,
            "sandbox_id": self.sandbox_id,
            "vitals": self.vitals.to_dict(),
            "logs": [log.to_dict() for log in self.logs],
            "client_context": self.client_context.to_dict(),
            "scrubbed_pii_count": self.scrubbed_pii_count,
            "created_at": self.created_at,
        }
        return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def to_dict(self) -> dict[str, object]:
        return {
            "bundle_id": self.bundle_id,
            "session_id": self.session_id,
            "sandbox_id": self.sandbox_id,
            "vitals": self.vitals.to_dict(),
            "logs": [log.to_dict() for log in self.logs],
            "client_context": self.client_context.to_dict(),
            "scrubbed_pii_count": self.scrubbed_pii_count,
            "checksum": self.checksum,
            "created_at": self.created_at,
        }
