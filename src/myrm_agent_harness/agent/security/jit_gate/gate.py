"""JIT Dual Verification Gate enforcing physical asset integrity and policy recency.

[POS]
Executes two-level fast metadata short-circuit and deep SHA-256 comparison
immediately prior to tool execution resumption. Prevents TOCTOU asset tampering
and stale approval replay across time.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from myrm_agent_harness.agent.security.jit_gate.models import (
    AssetContentFingerprint,
    AssetType,
    JITVerificationResult,
)

logger = logging.getLogger(__name__)


class AssetTamperedDuringApprovalError(Exception):
    """Raised when an asset was modified between approval creation and execution resumption."""

    def __init__(
        self,
        asset_identifier: str,
        expected_sha256: str,
        current_sha256: str,
        message: str = "",
    ) -> None:
        detail_msg = message or "file was modified during the approval waiting window"
        msg = (
            f"TOCTOU violation detected: {detail_msg} (Asset: '{asset_identifier}', "
            f"Expected SHA256: {expected_sha256[:12]}..., Current SHA256: {current_sha256[:12]}...)"
        )
        super().__init__(msg)
        self.asset_identifier = asset_identifier
        self.expected_sha256 = expected_sha256
        self.current_sha256 = current_sha256


class PolicyTightenedAtJITError(Exception):
    """Raised when the active security policy disallows execution at the resumption moment."""

    def __init__(self, action_identifier: str, reason: str = "") -> None:
        msg = (
            f"Policy enforcement gate blocked action '{action_identifier}' at JIT execution instant: "
            f"{reason or 'Current system security policy has been tightened and disallows this action.'}"
        )
        super().__init__(msg)
        self.action_identifier = action_identifier
        self.reason = reason


class JITDualVerificationGate:
    """Core verification gate for Just-In-Time execution instant assertions."""

    @staticmethod
    def normalize_text_bytes(content: bytes) -> bytes:
        """Normalize line endings to standard LF to prevent cross-platform false alarms."""
        return content.replace(b"\r\n", b"\n")

    @classmethod
    def compute_file_fingerprint(cls, file_path: Path) -> AssetContentFingerprint:
        """Compute an immutable content fingerprint for a physical workspace file."""
        if not file_path.exists():
            raise FileNotFoundError(f"Cannot fingerprint non-existent file: {file_path}")

        stat = file_path.stat()
        raw_bytes = file_path.read_bytes()
        normalized = cls.normalize_text_bytes(raw_bytes)
        content_hash = hashlib.sha256(normalized).hexdigest()

        return AssetContentFingerprint(
            asset_type=AssetType.FILE,
            asset_identifier=str(file_path.resolve()),
            content_sha256=content_hash,
            st_size=stat.st_size,
            st_mtime_ns=stat.st_mtime_ns,
        )

    @classmethod
    def compute_command_fingerprint(cls, command: str, tool_name: str) -> AssetContentFingerprint:
        """Compute deterministic canonical fingerprint for structured command or tool call."""
        canonical_payload = {
            "tool_name": tool_name.strip(),
            "command": " ".join(command.strip().split()),
        }
        encoded = json.dumps(canonical_payload, sort_keys=True).encode("utf-8")
        content_hash = hashlib.sha256(encoded).hexdigest()

        return AssetContentFingerprint(
            asset_type=AssetType.COMMAND,
            asset_identifier=f"{tool_name}:{command[:32]}",
            content_sha256=content_hash,
        )

    @classmethod
    def verify_physical_asset_untampered(
        cls,
        fingerprint: AssetContentFingerprint,
        current_path: Path,
    ) -> JITVerificationResult:
        """Verify that the physical asset matches the fingerprint captured during approval creation."""
        if not current_path.exists():
            return JITVerificationResult(
                is_valid=False,
                failure_reason=f"Asset was deleted prior to execution: {current_path}",
                expected_sha256=fingerprint.content_sha256,
            )

        stat = current_path.stat()

        # Level 1: Fast metadata short-circuit (< 0.05ms)
        # If both size and nanosecond modification timestamp match, accept immediately
        if (
            fingerprint.st_size is not None
            and fingerprint.st_mtime_ns is not None
            and stat.st_size == fingerprint.st_size
            and stat.st_mtime_ns == fingerprint.st_mtime_ns
        ):
            return JITVerificationResult(
                is_valid=True,
                current_sha256=fingerprint.content_sha256,
                expected_sha256=fingerprint.content_sha256,
                details={"short_circuit_metadata_match": True},
            )

        # Level 2: Deep content SHA-256 verification (when metadata indicates change or was absent)
        raw_bytes = current_path.read_bytes()
        normalized = cls.normalize_text_bytes(raw_bytes)
        current_hash = hashlib.sha256(normalized).hexdigest()

        if current_hash != fingerprint.content_sha256:
            logger.warning(
                "JIT Gate: TOCTOU asset tampering detected on %s (expected %s, got %s)",
                current_path,
                fingerprint.content_sha256[:12],
                current_hash[:12],
            )
            return JITVerificationResult(
                is_valid=False,
                failure_reason="Content SHA-256 mismatch: file was modified while awaiting approval",
                current_sha256=current_hash,
                expected_sha256=fingerprint.content_sha256,
            )

        return JITVerificationResult(
            is_valid=True,
            current_sha256=current_hash,
            expected_sha256=fingerprint.content_sha256,
            details={"deep_sha256_match": True},
        )

    @classmethod
    def assert_jit_dual_verification(
        cls,
        fingerprint: AssetContentFingerprint | None,
        target_path: Path | None = None,
        is_policy_allowed: bool = True,
        policy_disallow_reason: str = "",
    ) -> None:
        """Assert both physical content integrity AND current policy recency at execution instant.

        Raises:
            AssetTamperedDuringApprovalError: If physical asset was modified during the window.
            PolicyTightenedAtJITError: If the system security policy disallows the action now.
        """
        # Assertion 1: Policy recency check
        if not is_policy_allowed:
            action_id = fingerprint.asset_identifier if fingerprint else "unspecified"
            logger.warning("JIT Gate: Policy tightened assertion failed for %s", action_id)
            raise PolicyTightenedAtJITError(action_id, policy_disallow_reason)

        # Assertion 2: Physical asset integrity check (if file fingerprint attached)
        if fingerprint is not None and fingerprint.asset_type == AssetType.FILE:
            check_path = target_path or Path(fingerprint.asset_identifier)
            res = cls.verify_physical_asset_untampered(fingerprint, check_path)
            if not res.is_valid:
                raise AssetTamperedDuringApprovalError(
                    asset_identifier=fingerprint.asset_identifier,
                    expected_sha256=res.expected_sha256 or "",
                    current_sha256=res.current_sha256 or "",
                    message=res.failure_reason or "",
                )
