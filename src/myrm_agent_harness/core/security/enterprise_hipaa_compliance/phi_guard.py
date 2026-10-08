"""
[POS] src/myrm_agent_harness/core/security/enterprise_hipaa_compliance/phi_guard.py
[INPUT] re, types
[OUTPUT] PhiDataSovereigntyFence
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging
import re

from .types import (
    BYOCompliantProvider,
    PhiScreeningResult,
    ProviderComplianceTier,
)

logger = logging.getLogger(__name__)

# Heuristic patterns for Protected Health Information (PHI)
_MRN_REGEX = re.compile(r"\b(?:MRN|Medical\s*Record\s*(?:Number|#)?)\s*[:#-]?\s*([A-Z0-9]{6,12})\b", re.IGNORECASE)
_SSN_REGEX = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_ICD10_REGEX = re.compile(r"\b(?:ICD-?10\s*[:#-]?\s*)?([A-TV-Z][0-9][0-9A-Z](?:\.[0-9A-Z]{1,4})?)\b")
_NPI_REGEX = re.compile(r"\b(?:NPI\s*[:#-]?\s*)?(1\d{9})\b")


class PhiDataSovereigntyFence:
    """Detects Protected Health Information (PHI), enforces BAA endpoints, and injects zero-training headers."""

    def __init__(self, initial_providers: tuple[BYOCompliantProvider, ...] | None = None) -> None:
        self._providers: dict[str, BYOCompliantProvider] = {}
        if initial_providers:
            for p in initial_providers:
                self.register_provider(p)

    def register_provider(self, provider: BYOCompliantProvider) -> None:
        """Register a Bring-Your-Own (BYO) model provider with executed BAA compliance terms."""
        self._providers[provider.provider_id] = provider
        logger.info(
            "Registered BYO compliant provider '%s' (%s, tier: %s)",
            provider.provider_id,
            provider.provider_name,
            provider.tier.value,
        )

    def get_provider(self, provider_id: str) -> BYOCompliantProvider | None:
        """Retrieve compliant provider record by ID."""
        return self._providers.get(provider_id)

    def list_providers(self) -> tuple[BYOCompliantProvider, ...]:
        """List all registered compliant providers."""
        return tuple(self._providers.values())

    def screen_phi(self, content: str) -> PhiScreeningResult:
        """Screen text payload for presence of Protected Health Information identifiers."""
        detected: list[str] = []
        sanitized = content

        if _MRN_REGEX.search(content):
            detected.append("MEDICAL_RECORD_NUMBER_MRN")
            sanitized = _MRN_REGEX.sub("[REDACTED_MRN]", sanitized)

        if _SSN_REGEX.search(content):
            detected.append("SOCIAL_SECURITY_NUMBER_SSN")
            sanitized = _SSN_REGEX.sub("[REDACTED_SSN]", sanitized)

        if _NPI_REGEX.search(content):
            detected.append("NATIONAL_PROVIDER_IDENTIFIER_NPI")
            sanitized = _NPI_REGEX.sub("[REDACTED_NPI]", sanitized)

        is_clean = len(detected) == 0
        diagnostic = (
            "No Protected Health Information (PHI) identifiers detected"
            if is_clean
            else f"Detected {len(detected)} PHI identifier categories"
        )

        return PhiScreeningResult(
            is_clean=is_clean,
            detected_phi_categories=tuple(detected),
            sanitized_content=sanitized,
            diagnostic=diagnostic,
        )

    def validate_egress_and_build_headers(
        self,
        provider_id: str,
        content: str,
    ) -> tuple[bool, dict[str, str], str]:
        """Assert egress compliance to target provider and construct mandatory zero-training headers."""
        provider = self._providers.get(provider_id)
        if not provider:
            return (
                False,
                {},
                f"Egress blocked: provider '{provider_id}' is not in the approved BYO-compliant registry",
            )

        phi_check = self.screen_phi(content)

        # Unverified public endpoints are strictly forbidden from receiving PHI data
        if provider.tier == ProviderComplianceTier.UNVERIFIED_PUBLIC and not phi_check.is_clean:
            return (
                False,
                {},
                (
                    f"Egress denied: provider '{provider.provider_name}' lacks signed BAA agreement "
                    f"and payload contains {len(phi_check.detected_phi_categories)} PHI categories"
                ),
            )

        # Construct mandatory zero-training and data sovereignty request headers
        headers: dict[str, str] = {
            "X-Opt-Out-Training": "true",
            "X-Data-Sovereignty": "hipaa-strict",
            "X-Compliance-Standard": "HIPAA-Security-Rule-2026",
        }
        if provider.baa_agreement_id:
            headers["X-BAA-Agreement-ID"] = provider.baa_agreement_id

        return (
            True,
            headers,
            f"Egress authorized under {provider.tier.value} governance policy",
        )
