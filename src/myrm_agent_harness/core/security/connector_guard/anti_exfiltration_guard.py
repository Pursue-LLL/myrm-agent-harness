"""Anti-Exfiltration SSRF Guard Engine."""

from __future__ import annotations

import logging
import threading
import uuid
from urllib.parse import urlsplit

from .allowlist_registry import ConnectorAllowlistRegistry
from .ssrf_sentinel import SsrfAnomalySentinel
from .types import (
    EnterpriseOutboundMode,
    ExfiltrationThreatAlert,
    GuardDecision,
    InspectionResult,
    OutboundTrafficInspection,
    ThreatKind,
)

logger = logging.getLogger(__name__)

_CREDENTIAL_HEADERS = frozenset(
    {
        "authorization",
        "cookie",
        "x-api-key",
        "x-token",
        "apikey",
        "x-auth-token",
        "x-myrm-connector-ref",
    }
)


class AntiExfiltrationGuard:
    """Core enforcement engine preventing credential exfiltration and SSRF probes.

    Enforces:
    1. Strict host and SNI binding to registered connector official endpoints.
    2. Fail-safe zero-credential stripping for unregistered outbound external targets.
    3. Immediate blocking and circuit breaker tripping on SSRF and token smuggling.
    """

    def __init__(
        self,
        registry: ConnectorAllowlistRegistry | None = None,
        sentinel: SsrfAnomalySentinel | None = None,
        mode: EnterpriseOutboundMode = EnterpriseOutboundMode.ZERO_CRED_PERMISSIVE,
    ) -> None:
        self.registry = registry or ConnectorAllowlistRegistry()
        self.sentinel = sentinel or SsrfAnomalySentinel()
        self.mode = mode
        self._lock = threading.Lock()
        self._tripped_sessions: set[str] = set()
        self._alerts: list[ExfiltrationThreatAlert] = []

    def inspect_traffic(
        self, traffic: OutboundTrafficInspection
    ) -> InspectionResult:
        """Inspect outbound traffic, detecting SSRF and deciding credential injection policy."""
        session_id = traffic.session_id or "default_session"

        # 1. Circuit Breaker Check
        with self._lock:
            if session_id in self._tripped_sessions:
                return InspectionResult(
                    decision=GuardDecision.BLOCK,
                    reason=f"Security circuit breaker is TRIPPED for session '{session_id}' due to prior exfiltration attempt",
                    detected_threat=ThreatKind.UNREGISTERED_HOST,
                    sanitized_headers={},
                    can_inject_credential=False,
                    matched_connector_id=None,
                )

        # 2. SSRF and Token Smuggling Sentinel Inspection
        threat_kind, threat_desc = self.sentinel.check_url(traffic.url)
        if threat_kind is not None:
            alert = ExfiltrationThreatAlert(
                alert_id=f"alert-{uuid.uuid4().hex[:12]}",
                session_id=session_id,
                url=traffic.url,
                threat_kind=threat_kind,
                description=threat_desc,
                blocked=True,
            )
            with self._lock:
                self._alerts.append(alert)
                # Trip circuit breaker on high-severity threats (Metadata SSRF or Token Smuggling)
                if threat_kind in (ThreatKind.SSRF_METADATA, ThreatKind.TOKEN_SMUGGLING):
                    self._tripped_sessions.add(session_id)
                    logger.critical(
                        "Circuit breaker TRIPPED for session %s: %s (%s)",
                        session_id,
                        threat_kind,
                        threat_desc,
                    )

            return InspectionResult(
                decision=GuardDecision.BLOCK,
                reason=f"Blocked by SSRF/Exfiltration Sentinel: {threat_desc}",
                detected_threat=threat_kind,
                sanitized_headers={},
                can_inject_credential=False,
                matched_connector_id=None,
            )

        # 3. Extract and verify hostname
        parsed = urlsplit(traffic.url)
        hostname = (parsed.hostname or "").lower().strip()

        matched_entry = self.registry.match_host(hostname, traffic.connector_id)

        # 4. Validated Connector Match: Allow Credential Injection
        if matched_entry is not None:
            if not self.registry.validate_url_scheme(traffic.url, matched_entry):
                return InspectionResult(
                    decision=GuardDecision.BLOCK,
                    reason=f"Insecure scheme '{parsed.scheme}' not allowed for connector '{matched_entry.connector_id}'",
                    detected_threat=ThreatKind.HOST_SPOOFING,
                    sanitized_headers={},
                    can_inject_credential=False,
                    matched_connector_id=matched_entry.connector_id,
                )

            return InspectionResult(
                decision=GuardDecision.INJECT_CREDENTIALS,
                reason=f"Destination host '{hostname}' strictly bound to connector '{matched_entry.connector_id}'",
                detected_threat=None,
                sanitized_headers=dict(traffic.headers),
                can_inject_credential=True,
                matched_connector_id=matched_entry.connector_id,
            )

        # 5. Host is not in registered connector allowlist
        if self.mode == EnterpriseOutboundMode.STRICT_BLOCK_UNREGISTERED:
            return InspectionResult(
                decision=GuardDecision.BLOCK,
                reason=f"Host '{hostname}' is not in connector allowlist under strict enterprise policy",
                detected_threat=ThreatKind.UNREGISTERED_HOST,
                sanitized_headers={},
                can_inject_credential=False,
                matched_connector_id=None,
            )

        # 6. Zero-Credential Permissive Mode: Strip all credentials to prevent exfiltration
        sanitized = {
            k: v
            for k, v in traffic.headers.items()
            if k.lower() not in _CREDENTIAL_HEADERS
        }
        return InspectionResult(
            decision=GuardDecision.ZERO_CREDENTIAL_ALLOW,
            reason=f"Host '{hostname}' allowed for open access with zero credentials (all auth headers stripped)",
            detected_threat=None,
            sanitized_headers=sanitized,
            can_inject_credential=False,
            matched_connector_id=None,
        )

    def get_alerts(
        self, session_id: str | None = None
    ) -> list[ExfiltrationThreatAlert]:
        """Return captured security alerts, optionally filtered by session."""
        with self._lock:
            if session_id:
                return [a for a in self._alerts if a.session_id == session_id]
            return list(self._alerts)

    def reset_circuit_breaker(self, session_id: str) -> bool:
        """Reset the circuit breaker for a given session."""
        with self._lock:
            if session_id in self._tripped_sessions:
                self._tripped_sessions.remove(session_id)
                return True
            return False

    def is_circuit_breaker_tripped(self, session_id: str) -> bool:
        """Check whether the circuit breaker is currently tripped for a session."""
        with self._lock:
            return session_id in self._tripped_sessions

    def clear(self) -> None:
        """Clear all internal states and alerts."""
        with self._lock:
            self._tripped_sessions.clear()
            self._alerts.clear()
