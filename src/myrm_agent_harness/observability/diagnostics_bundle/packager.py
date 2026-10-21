"""
[INPUT]: Raw incident logs, sandbox vitals, and client context.
[OUTPUT]: Scrubbed, HMAC-checksummed EncryptedDiagnosticBundle instances.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/diagnostics_bundle/packager.py
"""

import hashlib
import hmac
import re
import uuid
from datetime import UTC, datetime
from re import Pattern

from myrm_agent_harness.core.security.detection.pii_patterns import EMAIL_RE

from .models import (
    ClientContext,
    DiagnosticLogEvent,
    EncryptedDiagnosticBundle,
    SandboxVitals,
)

DEFAULT_HMAC_SECRET = "myrm-diagnostic-hmac-v1-secret"

# Compilation of PII and Secret masking regex patterns
PII_PATTERNS: list[tuple[Pattern[str], str]] = [
    # Bearer tokens
    (re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]{10,}", re.IGNORECASE), r"\1***REDACTED***"),
    # OpenAI / Anthropic-style API keys (sk-...)
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}", re.IGNORECASE), "sk-***REDACTED***"),
    # Key-value secret assignments
    (
        re.compile(
            r"""(?i)(["']?(?:access_key|secret_key|api_key|password|token|secret)["']?\s*[:=]\s*["']?)([^"'\s,}{]+)(["']?)"""
        ),
        r"\1***REDACTED***\3",
    ),
    # Email addresses
    (EMAIL_RE, "***@***.***"),
    # North American / international phone patterns
    (
        re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
        "***-***-****",
    ),
]


class DiagnosticBundlePackager:
    """
    Assembles, cleanses (PII scrub), and cryptographically signs
    in-app diagnostic packages for incident triage and ticketing.
    """

    def __init__(self, hmac_secret: str = DEFAULT_HMAC_SECRET, max_logs: int = 50) -> None:
        self._secret = hmac_secret.encode("utf-8")
        self._max_logs = max_logs

    def scrub_text(self, text: str) -> tuple[str, int]:
        """
        Redacts API keys, credentials, and PII from raw text strings.
        Returns the cleansed string and count of scrubbed items.
        """
        scrubbed = text
        total_scrubbed = 0
        for pattern, replacement in PII_PATTERNS:
            matches = len(pattern.findall(scrubbed))
            if matches > 0:
                scrubbed = pattern.sub(replacement, scrubbed)
                total_scrubbed += matches
        return scrubbed, total_scrubbed

    def scrub_log_event(self, event: DiagnosticLogEvent) -> tuple[DiagnosticLogEvent, int]:
        """Cleanses message and metadata inside a diagnostic log event."""
        scrubbed_msg, msg_count = self.scrub_text(event.message)
        scrubbed_meta: dict[str, str] = {}
        meta_count = 0

        for k, v in event.metadata.items():
            s_val, cnt = self.scrub_text(v)
            scrubbed_meta[k] = s_val
            meta_count += cnt

        clean_event = DiagnosticLogEvent(
            timestamp=event.timestamp,
            level=event.level,
            subsystem=event.subsystem,
            message=scrubbed_msg,
            metadata=scrubbed_meta,
        )
        return clean_event, (msg_count + meta_count)

    def compute_hmac(self, canonical_bytes: bytes) -> str:
        """Computes SHA-256 HMAC digest for canonical bundle serialization."""
        return hmac.new(self._secret, canonical_bytes, hashlib.sha256).hexdigest()

    def package(
        self,
        session_id: str,
        sandbox_id: str,
        vitals: SandboxVitals,
        raw_logs: list[DiagnosticLogEvent],
        client_context: ClientContext,
        bundle_id: str | None = None,
    ) -> EncryptedDiagnosticBundle:
        """
        Takes raw logs, scrubs sensitive content, slices down to max_logs,
        and produces an immutable signed EncryptedDiagnosticBundle.
        """
        bid = bundle_id or f"bundle_{uuid.uuid4().hex[:12]}"
        now_iso = datetime.now(UTC).isoformat()

        # Keep only the most recent N logs to avoid payload bloat
        targeted_logs = raw_logs[-self._max_logs :] if len(raw_logs) > self._max_logs else list(raw_logs)

        clean_logs: list[DiagnosticLogEvent] = []
        total_pii_scrubbed = 0

        for event in targeted_logs:
            cleansed, scrub_count = self.scrub_log_event(event)
            clean_logs.append(cleansed)
            total_pii_scrubbed += scrub_count

        temp_bundle = EncryptedDiagnosticBundle(
            bundle_id=bid,
            session_id=session_id,
            sandbox_id=sandbox_id,
            vitals=vitals,
            logs=clean_logs,
            client_context=client_context,
            scrubbed_pii_count=total_pii_scrubbed,
            checksum="",
            created_at=now_iso,
        )

        checksum = self.compute_hmac(temp_bundle.canonical_bytes())
        temp_bundle.checksum = checksum
        return temp_bundle

    def verify_integrity(self, bundle: EncryptedDiagnosticBundle) -> bool:
        """Verifies if the bundle's HMAC matches its payload."""
        expected_checksum = self.compute_hmac(bundle.canonical_bytes())
        return hmac.compare_digest(bundle.checksum, expected_checksum)
