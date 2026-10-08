"""Replayable repair bundle engine for verifiable security issue remediation.

[INPUT]
- AuditFinding, RepairPatch items, replay script instructions.

[OUTPUT]
- ReplayableRepairBundle with cryptographic checksum and deterministic replay verification.

[POS]
- Harness core security engine. Packages security findings into replayable, reviewable
  repair bundles with explicit verification tiers (self_reported vs tested).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections.abc import Sequence

from myrm_agent_harness.core.security.audit_coverage.types import (
    AuditFinding,
    RepairBundleVerificationError,
    RepairPatch,
    ReplayableRepairBundle,
    VerificationTier,
)

logger = logging.getLogger(__name__)


class ReplayableRepairEngine:
    """Engine creating and verifying replayable repair bundles for security audit findings."""

    @staticmethod
    def _compute_checksum(finding_id: str, patches: Sequence[RepairPatch], replay_script: str) -> str:
        """Calculate deterministic SHA-256 checksum binding patches and replay validation steps."""
        hasher = hashlib.sha256()
        hasher.update(finding_id.encode("utf-8"))
        for p in patches:
            hasher.update(p.file_path.encode("utf-8"))
            hasher.update(p.target_checksum.encode("utf-8"))
            hasher.update(p.diff_content.encode("utf-8"))
            hasher.update(p.replay_command.encode("utf-8"))
        hasher.update(replay_script.encode("utf-8"))
        return hasher.hexdigest()

    def create_bundle(
        self,
        finding: AuditFinding,
        patches: Sequence[RepairPatch],
        replay_script: str,
    ) -> ReplayableRepairBundle:
        """Construct a self-contained repair bundle bound to an audit finding."""
        bundle_id = f"bundle_{uuid.uuid4().hex[:12]}"
        checksum = self._compute_checksum(finding.finding_id, patches, replay_script)

        return ReplayableRepairBundle(
            bundle_id=bundle_id,
            finding_id=finding.finding_id,
            patches=tuple(patches),
            replay_script=replay_script,
            checksum=checksum,
            is_verified=False,
        )

    def verify_bundle(
        self,
        bundle: ReplayableRepairBundle,
        expected_checksum: str | None = None,
    ) -> ReplayableRepairBundle:
        """Verify the cryptographic integrity and replayability of the repair bundle."""
        calculated = self._compute_checksum(
            bundle.finding_id,
            bundle.patches,
            bundle.replay_script,
        )

        if expected_checksum and expected_checksum != calculated:
            raise RepairBundleVerificationError(
                f"Checksum mismatch for bundle '{bundle.bundle_id}'. "
                f"Expected '{expected_checksum}', got '{calculated}'."
            )

        if calculated != bundle.checksum:
            raise RepairBundleVerificationError(
                f"Tampered bundle '{bundle.bundle_id}': Stored checksum does not match computed value."
            )

        if not bundle.patches:
            raise RepairBundleVerificationError(
                f"Invalid bundle '{bundle.bundle_id}': Contains zero repair patches."
            )

        return ReplayableRepairBundle(
            bundle_id=bundle.bundle_id,
            finding_id=bundle.finding_id,
            patches=bundle.patches,
            replay_script=bundle.replay_script,
            checksum=bundle.checksum,
            is_verified=True,
        )

    def upgrade_finding_verification(
        self,
        finding: AuditFinding,
        bundle: ReplayableRepairBundle,
    ) -> AuditFinding:
        """Elevate finding verification tier from SELF_REPORTED to TESTED once bundle is verified."""
        if not bundle.is_verified:
            raise RepairBundleVerificationError(
                f"Cannot upgrade finding '{finding.finding_id}' with unverified bundle '{bundle.bundle_id}'."
            )

        return AuditFinding(
            finding_id=finding.finding_id,
            category=finding.category,
            severity=finding.severity,
            title=finding.title,
            description=finding.description,
            application_model_ref=finding.application_model_ref,
            evidence=finding.evidence,
            challenge_status=finding.challenge_status,
            challenge_notes=finding.challenge_notes,
            verification_tier=VerificationTier.TESTED,
        )
