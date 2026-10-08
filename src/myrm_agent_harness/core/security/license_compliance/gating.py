"""License compliance gating evaluator and policy enforcement engine.

[INPUT]
- AssetLicenseDescriptor, DeploymentEnvironment, and policy override flags.

[OUTPUT]
- LicenseComplianceVerdict detailing admission decision, legal rationale, and override capability.

[POS]
- Harness core security policy engine safeguarding cloud commercial and local runtime boundaries.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.license_compliance.types import (
    AssetLicenseDescriptor,
    CopyleftBlockedError,
    DeploymentEnvironment,
    LicenseComplianceVerdict,
    LicenseGateDecision,
    LicenseRiskTier,
    UnknownLicenseBlockedError,
)


class LicenseComplianceGate:
    """Deployment-aware policy gate evaluating third-party asset licenses."""

    def __init__(self, default_environment: DeploymentEnvironment = DeploymentEnvironment.LOCAL_DESKTOP) -> None:
        self._default_environment = default_environment

    def evaluate(
        self,
        asset: AssetLicenseDescriptor,
        environment: DeploymentEnvironment | None = None,
        allow_override: bool = False,
    ) -> LicenseComplianceVerdict:
        """Evaluate license compatibility against deployment environment rules."""
        env = environment or self._default_environment
        license_meta = asset.detected_license
        tier = license_meta.risk_tier

        if tier == LicenseRiskTier.PERMISSIVE:
            return LicenseComplianceVerdict(
                decision=LicenseGateDecision.ALLOWED,
                asset_id=asset.asset_id,
                detected_license=license_meta,
                environment=env,
                reason=f"Permissive license '{license_meta.spdx_id}' is safe for all deployment targets.",
                can_override=False,
            )

        if tier == LicenseRiskTier.WEAK_COPYLEFT:
            if env == DeploymentEnvironment.CLOUD_COMMERCIAL:
                return LicenseComplianceVerdict(
                    decision=LicenseGateDecision.WARNING_PROCEED,
                    asset_id=asset.asset_id,
                    detected_license=license_meta,
                    environment=env,
                    reason=(
                        f"Weak copyleft license '{license_meta.spdx_id}' permitted in cloud commercial "
                        "deployments under isolation/linking, but modifications must remain disclosed."
                    ),
                    can_override=True,
                )
            return LicenseComplianceVerdict(
                decision=LicenseGateDecision.ALLOWED,
                asset_id=asset.asset_id,
                detected_license=license_meta,
                environment=env,
                reason=f"Weak copyleft license '{license_meta.spdx_id}' allowed for local execution.",
                can_override=False,
            )

        if tier == LicenseRiskTier.STRONG_COPYLEFT:
            if env == DeploymentEnvironment.CLOUD_COMMERCIAL:
                if allow_override:
                    return LicenseComplianceVerdict(
                        decision=LicenseGateDecision.WARNING_PROCEED,
                        asset_id=asset.asset_id,
                        detected_license=license_meta,
                        environment=env,
                        reason=(
                            f"Strong copyleft license '{license_meta.spdx_id}' permitted under explicit "
                            "administrative risk override."
                        ),
                        can_override=True,
                        audit_notes="ADMIN_OVERRIDE_GRANTED",
                    )
                return LicenseComplianceVerdict(
                    decision=LicenseGateDecision.BLOCKED_COPYLEFT_RESTRICTION,
                    asset_id=asset.asset_id,
                    detected_license=license_meta,
                    environment=env,
                    reason=(
                        f"Viral copyleft license '{license_meta.spdx_id}' is strictly blocked in cloud commercial "
                        "environments to prevent derivative licensing exposure."
                    ),
                    can_override=True,
                )
            # In local desktop: inform user with warning, but do not block personal evaluation
            return LicenseComplianceVerdict(
                decision=LicenseGateDecision.WARNING_PROCEED,
                asset_id=asset.asset_id,
                detected_license=license_meta,
                environment=env,
                reason=(
                    f"Strong copyleft license '{license_meta.spdx_id}' detected. Permitted for local desktop "
                    "development; distribution carries viral licensing obligations."
                ),
                can_override=True,
            )

        if tier == LicenseRiskTier.PROPRIETARY:
            if env == DeploymentEnvironment.CLOUD_COMMERCIAL and not allow_override:
                return LicenseComplianceVerdict(
                    decision=LicenseGateDecision.WARNING_PROCEED,
                    asset_id=asset.asset_id,
                    detected_license=license_meta,
                    environment=env,
                    reason=f"Proprietary license '{license_meta.spdx_id}' requires verified commercial license keys.",
                    can_override=True,
                )
            return LicenseComplianceVerdict(
                decision=LicenseGateDecision.ALLOWED,
                asset_id=asset.asset_id,
                detected_license=license_meta,
                environment=env,
                reason="Proprietary terms acknowledged.",
                can_override=False,
            )

        # UNKNOWN tier
        if env == DeploymentEnvironment.CLOUD_COMMERCIAL:
            if allow_override:
                return LicenseComplianceVerdict(
                    decision=LicenseGateDecision.WARNING_PROCEED,
                    asset_id=asset.asset_id,
                    detected_license=license_meta,
                    environment=env,
                    reason="Unknown license permitted under explicit administrative risk override.",
                    can_override=True,
                    audit_notes="ADMIN_OVERRIDE_GRANTED",
                )
            return LicenseComplianceVerdict(
                decision=LicenseGateDecision.BLOCKED_UNKNOWN_LICENSE,
                asset_id=asset.asset_id,
                detected_license=license_meta,
                environment=env,
                reason="Unidentified or missing license is blocked under cloud commercial zero-trust policies.",
                can_override=True,
            )

        return LicenseComplianceVerdict(
            decision=LicenseGateDecision.WARNING_PROCEED,
            asset_id=asset.asset_id,
            detected_license=license_meta,
            environment=env,
            reason="Unidentified license detected. Exercising caution during local execution.",
            can_override=True,
        )

    def assert_admissible(
        self,
        asset: AssetLicenseDescriptor,
        environment: DeploymentEnvironment | None = None,
        allow_override: bool = False,
    ) -> LicenseComplianceVerdict:
        """Evaluate and raise exception if the license verdict blocks admission."""
        verdict = self.evaluate(asset=asset, environment=environment, allow_override=allow_override)
        if verdict.decision == LicenseGateDecision.BLOCKED_COPYLEFT_RESTRICTION:
            raise CopyleftBlockedError(f"Asset '{asset.asset_id}' blocked: {verdict.reason}")
        if verdict.decision == LicenseGateDecision.BLOCKED_UNKNOWN_LICENSE:
            raise UnknownLicenseBlockedError(f"Asset '{asset.asset_id}' blocked: {verdict.reason}")
        return verdict
