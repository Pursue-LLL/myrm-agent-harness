"""Security vector inspection probes for host isolation, mounts, binaries, and TLS.

[POS]
Low-overhead vector probes evaluating runtime sandbox constraints,
file-boundary penetrations, binary SHA-256 integrity, and outbound TLS certificates.
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import socket
import ssl
from pathlib import Path

from myrm_agent_harness.agent.security.attestation.models import (
    AttestationSeverity,
    VectorCategory,
    VectorCheckResult,
)

logger = logging.getLogger(__name__)


class HostIsolationProbe:
    """Probes host isolation markers and unauthorized sensitive mount penetrations."""

    DANGEROUS_HOST_PATHS: tuple[str, ...] = (
        "/var/run/docker.sock",
        "/etc/shadow",
        "/etc/sudoers",
    )

    @classmethod
    def audit_dangerous_mounts(cls) -> list[VectorCheckResult]:
        """Check if high-risk host system files or docker sockets leaked into the environment."""
        results: list[VectorCheckResult] = []

        for p_str in cls.DANGEROUS_HOST_PATHS:
            p = Path(p_str)
            exists = p.exists()
            is_writable = os.access(p, os.W_OK) if exists else False

            if exists and is_writable:
                results.append(
                    VectorCheckResult(
                        vector=VectorCategory.MOUNT_BOUNDARY,
                        target=p_str,
                        is_valid=False,
                        severity=AttestationSeverity.CRITICAL,
                        error_message=f"Critical boundary penetration: host sensitive path '{p_str}' is writable!",
                        details={"exists": "true", "writable": "true"},
                    )
                )
            else:
                results.append(
                    VectorCheckResult(
                        vector=VectorCategory.MOUNT_BOUNDARY,
                        target=p_str,
                        is_valid=True,
                        severity=AttestationSeverity.INFO,
                        details={"exists": str(exists).lower(), "writable": str(is_writable).lower()},
                    )
                )

        return results

    @classmethod
    def audit_host_fingerprint(cls) -> VectorCheckResult:
        """Capture immutable host architecture and environment signature."""
        uname = platform.uname()
        fp = f"{uname.system}-{uname.machine}-{uname.node}"
        return VectorCheckResult(
            vector=VectorCategory.HOST_ISOLATION,
            target="host_architecture",
            is_valid=True,
            severity=AttestationSeverity.INFO,
            actual_digest=hashlib.sha256(fp.encode("utf-8")).hexdigest(),
            details={"system": uname.system, "machine": uname.machine},
        )


class BinaryIntegrityProbe:
    """Probes cryptographic SHA-256 integrity of core runtime binaries and scripts."""

    @classmethod
    def compute_file_sha256(cls, file_path: Path) -> str:
        """Stream file bytes and compute SHA-256 digest with low memory footprint."""
        sha = hashlib.sha256()
        with file_path.open("rb") as f:
            while chunk := f.read(65536):
                sha.update(chunk)
        return sha.hexdigest()

    @classmethod
    def verify_binary(
        cls,
        target_path: Path,
        expected_sha256: str | None = None,
    ) -> VectorCheckResult:
        """Verify binary existence and compare with expected cryptographic baseline."""
        target_str = str(target_path.resolve())
        if not target_path.exists():
            return VectorCheckResult(
                vector=VectorCategory.BINARY_INTEGRITY,
                target=target_str,
                is_valid=False,
                severity=AttestationSeverity.CRITICAL,
                error_message=f"Required runtime executable or tool binary is missing: {target_str}",
            )

        actual_sha = cls.compute_file_sha256(target_path)

        if expected_sha256 is not None and actual_sha != expected_sha256:
            return VectorCheckResult(
                vector=VectorCategory.BINARY_INTEGRITY,
                target=target_str,
                is_valid=False,
                severity=AttestationSeverity.CRITICAL,
                expected_digest=expected_sha256,
                actual_digest=actual_sha,
                error_message=f"Binary tampering detected! SHA-256 mismatch for {target_str}",
            )

        return VectorCheckResult(
            vector=VectorCategory.BINARY_INTEGRITY,
            target=target_str,
            is_valid=True,
            severity=AttestationSeverity.INFO,
            expected_digest=expected_sha256,
            actual_digest=actual_sha,
        )


class ConnectionTLSPinningProbe:
    """Probes TLS certificates of external API and model endpoints to prevent MITM proxy attacks."""

    @classmethod
    def verify_endpoint_tls(
        cls,
        hostname: str,
        port: int = 443,
        expected_pin_sha256: str | None = None,
        timeout_seconds: float = 3.0,
    ) -> VectorCheckResult:
        """Extract public key certificate and verify against pinned SHA-256 fingerprint."""
        ctx = ssl.create_default_context()
        try:
            with socket.create_connection((hostname, port), timeout=timeout_seconds) as sock:
                with ctx.wrap_socket(sock, server_hostname=hostname) as ssock:
                    der_cert = ssock.getpeercert(binary_form=True)
                    if not der_cert:
                        return VectorCheckResult(
                            vector=VectorCategory.OUTBOUND_TLS,
                            target=f"{hostname}:{port}",
                            is_valid=False,
                            severity=AttestationSeverity.CRITICAL,
                            error_message="Failed to retrieve binary peer certificate from TLS handshake",
                        )

                    cert_sha256 = hashlib.sha256(der_cert).hexdigest()

                    if expected_pin_sha256 is not None and cert_sha256 != expected_pin_sha256:
                        return VectorCheckResult(
                            vector=VectorCategory.OUTBOUND_TLS,
                            target=f"{hostname}:{port}",
                            is_valid=False,
                            severity=AttestationSeverity.CRITICAL,
                            expected_digest=expected_pin_sha256,
                            actual_digest=cert_sha256,
                            error_message=(
                                f"TLS Pinning Mismatch for {hostname}! Possible MITM interception, proxy "
                                f"injection, or unauthorized certificate replacement."
                            ),
                        )

                    return VectorCheckResult(
                        vector=VectorCategory.OUTBOUND_TLS,
                        target=f"{hostname}:{port}",
                        is_valid=True,
                        severity=AttestationSeverity.INFO,
                        expected_digest=expected_pin_sha256,
                        actual_digest=cert_sha256,
                    )
        except Exception as exc:
            logger.warning("[TLS_PROBE] Handshake failed with %s:%d: %s", hostname, port, exc)
            return VectorCheckResult(
                vector=VectorCategory.OUTBOUND_TLS,
                target=f"{hostname}:{port}",
                is_valid=False,
                severity=AttestationSeverity.WARNING,
                error_message=f"TLS handshake/connection failed: {exc}",
            )
