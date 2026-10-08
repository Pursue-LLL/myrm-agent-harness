"""Artifact exfiltration shield.

Prevents sandbox screenshots, credentials, and sensitive artifacts from being
silently uploaded to public GitHub repositories, public pastebins, or unvetted endpoints.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import datetime
import hashlib
import re
from collections.abc import Sequence

from .types import (
    ArtifactExfiltrationAudit,
    ArtifactSecurityClassification,
    EgressDestinationTrust,
)

_SENSITIVE_FILENAME_PATTERN = re.compile(
    r"(?i)(screenshot|screen_capture|\.png$|\.jpg$|id_rsa|credentials|\.env|dump|secret|key\.pem|token)"
)

_PUBLIC_UNTRUSTED_TARGET_PATTERN = re.compile(
    r"(?i)(github\.com/(?!internal|private)[^/\s]+/[^/\s]+|imgur\.com|pastebin\.com|catbox\.moe|0x0\.st|transfer\.sh|bashupload)"
)


class ArtifactExfiltrationShield:
    """Monitors outbound network egress and prevents artifact exfiltration."""

    def __init__(
        self,
        allowlisted_destinations: Sequence[str] | None = None,
        enforce_strict_screenshot_containment: bool = True,
    ) -> None:
        self.allowlisted_destinations = set(allowlisted_destinations or [])
        self.enforce_strict_screenshot_containment = enforce_strict_screenshot_containment

    def classify_artifact(
        self,
        artifact_id: str,
        artifact_name: str,
        content_bytes: bytes,
        explicit_classification: ArtifactSecurityClassification | None = None,
    ) -> ArtifactSecurityClassification:
        """Classify security level of an artifact based on filename and contents."""
        if explicit_classification is not None:
            return explicit_classification

        if _SENSITIVE_FILENAME_PATTERN.search(artifact_name):
            return ArtifactSecurityClassification.RESTRICTED_ARTIFACT

        # Inspect bytes for private key or credential markers
        if b"PRIVATE KEY" in content_bytes or b"AWS_SECRET_ACCESS_KEY" in content_bytes:
            return ArtifactSecurityClassification.RESTRICTED_ARTIFACT

        return ArtifactSecurityClassification.INTERNAL

    def evaluate_egress(
        self,
        artifact_id: str,
        artifact_name: str,
        content_bytes: bytes,
        target_destination: str,
        explicit_classification: ArtifactSecurityClassification | None = None,
    ) -> ArtifactExfiltrationAudit:
        """Evaluate an attempted egress operation and block unauthorized public uploads."""
        now_iso = datetime.datetime.now(datetime.UTC).isoformat()
        sha256_hash = hashlib.sha256(content_bytes).hexdigest()

        classification = self.classify_artifact(
            artifact_id=artifact_id,
            artifact_name=artifact_name,
            content_bytes=content_bytes,
            explicit_classification=explicit_classification,
        )

        destination_trust = self._evaluate_destination_trust(target_destination)

        # Enforce hard block if restricted artifact is aimed at untrusted external public destination
        if (
            classification == ArtifactSecurityClassification.RESTRICTED_ARTIFACT
            and destination_trust == EgressDestinationTrust.UNTRUSTED_PUBLIC_EXTERNAL
        ):
            return ArtifactExfiltrationAudit(
                    artifact_id=artifact_id,
                    artifact_name=artifact_name,
                    classification=classification,
                    target_destination=target_destination,
                    destination_trust=destination_trust,
                    is_blocked=True,
                    violation_reason=(
                        f"Blocked: Attempted to exfiltrate private artifact '{artifact_name}' "
                        f"to public external destination '{target_destination}'."
                    ),
                    sha256_hash=sha256_hash,
                    evaluated_at=now_iso,
                )

        return ArtifactExfiltrationAudit(
            artifact_id=artifact_id,
            artifact_name=artifact_name,
            classification=classification,
            target_destination=target_destination,
            destination_trust=destination_trust,
            is_blocked=False,
            violation_reason="",
            sha256_hash=sha256_hash,
            evaluated_at=now_iso,
        )

    def _evaluate_destination_trust(self, target_destination: str) -> EgressDestinationTrust:
        """Evaluate trust classification of destination URI or hostname."""
        target_clean = target_destination.strip()

        # Check explicit allowlist
        if any(allowed in target_clean for allowed in self.allowlisted_destinations):
            return EgressDestinationTrust.ALLOWLISTED_INTERNAL

        if "private-internal" in target_clean or "myrm.corp" in target_clean:
            return EgressDestinationTrust.ALLOWLISTED_INTERNAL

        if "github.com/myrm-private" in target_clean:
            return EgressDestinationTrust.AUTHORIZED_PRIVATE_REPO

        if _PUBLIC_UNTRUSTED_TARGET_PATTERN.search(target_clean):
            return EgressDestinationTrust.UNTRUSTED_PUBLIC_EXTERNAL

        # Default external URLs to untrusted public
        if target_clean.startswith("http://") or target_clean.startswith("https://"):
            return EgressDestinationTrust.UNTRUSTED_PUBLIC_EXTERNAL

        return EgressDestinationTrust.UNTRUSTED_PUBLIC_EXTERNAL
