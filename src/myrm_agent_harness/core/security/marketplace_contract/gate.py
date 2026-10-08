"""Marketplace admission gate enforcing organization source allowlists and capability restrictions.

[INPUT]
- MarketplaceManifestItem, AdmissionPolicy.

[OUTPUT]
- AdmissionVerdict and fail-closed admission assertions.

[POS]
- Harness core security engine. Gating mechanism enforcing organization-wide source pinning,
  tier classification, and capability isolation prior to installation.
"""

from __future__ import annotations

import logging

from myrm_agent_harness.core.security.marketplace_contract.types import (
    AdmissionPolicy,
    AdmissionVerdict,
    DisallowedCapabilityError,
    DisallowedTierError,
    MarketplaceManifestItem,
    SourcePinningMissingError,
)
from myrm_agent_harness.core.security.marketplace_contract.validator import (
    ManifestContractValidator,
)

logger = logging.getLogger(__name__)


class MarketplaceAdmissionGate:
    """Enforces organization admission policies against marketplace packages."""

    def __init__(
        self,
        policy: AdmissionPolicy | None = None,
        validator: ManifestContractValidator | None = None,
    ) -> None:
        self._policy = policy or AdmissionPolicy()
        self._validator = validator or ManifestContractValidator()

    @property
    def policy(self) -> AdmissionPolicy:
        """Current organization admission policy."""
        return self._policy

    def set_policy(self, policy: AdmissionPolicy) -> None:
        """Update active admission policy."""
        self._policy = policy

    def evaluate_manifest(self, manifest: MarketplaceManifestItem) -> AdmissionVerdict:
        """Evaluate package manifest against admission policies and capability rules."""
        violations: list[str] = []

        # 1. Enforce source pinning
        if self._policy.enforce_strict_pinning and (
            not manifest.source_sha or not self._validator.is_valid_sha(manifest.source_sha)
        ):
            violations.append(
                f"Missing or invalid immutable SHA-1/SHA-256 pin: '{manifest.source_sha}'"
            )

        # 2. Check allowed sources allowlist if configured
        if self._policy.allowed_sources:
            is_source_allowed = any(
                src in manifest.repo_url or src == manifest.source_sha
                for src in self._policy.allowed_sources
            )
            if not is_source_allowed:
                violations.append(
                    f"Repository source '{manifest.repo_url}' is not in allowed sources allowlist "
                    f"{self._policy.allowed_sources}"
                )

        # 3. Check allowed tiers if configured
        if self._policy.allowed_tiers and manifest.tier not in self._policy.allowed_tiers:
            violations.append(
                f"Tier '{manifest.tier}' is disallowed by organization policy. "
                f"Allowed tiers: {[t.value for t in self._policy.allowed_tiers]}"
            )

        # 4. Check disallowed capabilities
        if self._policy.disallowed_capabilities:
            for dis in self._policy.disallowed_capabilities:
                if dis in manifest.capabilities.provides_middleware:
                    violations.append(f"Forbidden middleware capability requested: '{dis}'")
                if dis in manifest.capabilities.provides_hooks:
                    violations.append(f"Forbidden lifecycle hook capability requested: '{dis}'")
                if dis in manifest.capabilities.provides_tools:
                    violations.append(f"Forbidden tool capability requested: '{dis}'")

        is_admitted = len(violations) == 0
        reason = (
            "Package manifest complies with all organization admission policies."
            if is_admitted
            else f"Admission denied: {'; '.join(violations)}"
        )

        return AdmissionVerdict(
            is_admitted=is_admitted,
            package_id=manifest.package_id,
            reason=reason,
            violations=tuple(violations),
        )

    def assert_admission(self, manifest: MarketplaceManifestItem) -> None:
        """Assert that package is admitted, raising specific domain error if denied."""
        verdict = self.evaluate_manifest(manifest)
        if verdict.is_admitted:
            return

        for violation in verdict.violations:
            if "SHA" in violation:
                raise SourcePinningMissingError(violation)
            if "Tier" in violation:
                raise DisallowedTierError(violation)
            if "Forbidden" in violation:
                raise DisallowedCapabilityError(violation)

        raise DisallowedTierError(verdict.reason)
