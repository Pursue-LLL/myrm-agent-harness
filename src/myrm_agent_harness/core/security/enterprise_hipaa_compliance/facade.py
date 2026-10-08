"""
[POS] src/myrm_agent_harness/core/security/enterprise_hipaa_compliance/facade.py
[INPUT] types, audit_chain, phi_guard
[OUTPUT] EnterpriseHipaaComplianceFacade
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import logging

from .audit_chain import HipaaAuditChainEngine
from .phi_guard import PhiDataSovereigntyFence
from .types import (
    BYOCompliantProvider,
    ComplianceExportPackage,
    ComplianceStandard,
    EnterpriseComplianceMetrics,
    HipaaAuditChainEntry,
    PhiScreeningResult,
    ProviderComplianceTier,
)

logger = logging.getLogger(__name__)


class EnterpriseHipaaComplianceFacade:
    """Unified entrypoint for enterprise BAA model endpoints, HIPAA audit chains, and PHI fences."""

    def __init__(
        self,
        audit_engine: HipaaAuditChainEngine | None = None,
        phi_fence: PhiDataSovereigntyFence | None = None,
    ) -> None:
        self._audit_engine = audit_engine or HipaaAuditChainEngine()
        self._phi_fence = phi_fence or PhiDataSovereigntyFence(
            initial_providers=(
                BYOCompliantProvider(
                    provider_id="azure-openai-enterprise-eastus",
                    provider_name="Azure OpenAI Service (HIPAA Compliant)",
                    base_url="https://corp-azure-openai.openai.azure.com",
                    tier=ProviderComplianceTier.VERIFIED_BAA_SIGNED,
                    baa_agreement_id="BAA-MSFT-CORP-2026-X9",
                    is_zero_training_mandated=True,
                ),
                BYOCompliantProvider(
                    provider_id="private-vllm-on-prem",
                    provider_name="Self-Hosted On-Prem vLLM Cluster",
                    base_url="http://vllm-cluster.internal:8000",
                    tier=ProviderComplianceTier.PRIVATE_VLLM_AIRGAP,
                    baa_agreement_id=None,
                    is_zero_training_mandated=True,
                ),
            )
        )
        self._metrics = EnterpriseComplianceMetrics(
            providers_registered_total=len(self._phi_fence.list_providers())
        )

    @property
    def metrics(self) -> EnterpriseComplianceMetrics:
        """Operational telemetry metrics."""
        return self._metrics

    def register_compliant_provider(self, provider: BYOCompliantProvider) -> None:
        """Register a custom Bring-Your-Own (BYO) model endpoint."""
        self._phi_fence.register_provider(provider)
        self._metrics.providers_registered_total += 1

    def get_compliant_provider(self, provider_id: str) -> BYOCompliantProvider | None:
        """Fetch provider registration details by ID."""
        return self._phi_fence.get_provider(provider_id)

    def list_compliant_providers(self) -> tuple[BYOCompliantProvider, ...]:
        """Fetch all registered compliant providers."""
        return self._phi_fence.list_providers()

    def screen_phi_content(self, content: str) -> PhiScreeningResult:
        """Inspect inbound/outbound text for Protected Health Information."""
        res = self._phi_fence.screen_phi(content)
        if not res.is_clean:
            self._metrics.phi_violations_blocked_total += 1
        return res

    def validate_provider_egress(
        self,
        provider_id: str,
        content: str,
    ) -> tuple[bool, dict[str, str], str]:
        """Assert egress compliance to target provider and inject zero-training headers."""
        allowed, headers, diag = self._phi_fence.validate_egress_and_build_headers(
            provider_id=provider_id, content=content
        )
        if allowed:
            self._metrics.zero_training_headers_injected_total += 1
        else:
            self._metrics.unverified_egress_denied_total += 1
        return allowed, headers, diag

    def record_audit_event(
        self,
        event_type: str,
        agent_id: str,
        session_id: str,
        action_summary: str,
        phi_detected: bool = False,
        timestamp: float | None = None,
    ) -> HipaaAuditChainEntry:
        """Record an immutably hashed lifecycle action in the HIPAA audit ledger."""
        entry = self._audit_engine.append_event(
            event_type=event_type,
            agent_id=agent_id,
            session_id=session_id,
            action_summary=action_summary,
            phi_detected=phi_detected,
            timestamp=timestamp,
        )
        self._metrics.audit_events_recorded_total += 1
        return entry

    def verify_audit_integrity(self) -> tuple[bool, str]:
        """Verify sequential SHA-256 integrity across recorded audit ledger entries."""
        return self._audit_engine.verify_chain_integrity()

    def export_compliance_package(
        self,
        standard: ComplianceStandard = ComplianceStandard.HIPAA,
        current_time: float | None = None,
    ) -> ComplianceExportPackage:
        """Export verifiable compliance proof package."""
        pkg = self._audit_engine.export_package(standard=standard, current_time=current_time)
        self._metrics.compliance_exports_generated_total += 1
        return pkg
