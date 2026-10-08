"""
[POS] src/myrm_agent_harness/core/security/enterprise_hipaa_compliance/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] ComplianceStandard, ProviderComplianceTier, BYOCompliantProvider, HipaaAuditChainEntry, PhiScreeningResult, ComplianceExportPackage, EnterpriseComplianceMetrics
Domain types for Enterprise BAA/HIPAA Compliance Conduit & Data Sovereignty Fence Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ComplianceStandard(StrEnum):
    """Supported enterprise data governance and healthcare compliance standards."""

    HIPAA = "hipaa"
    BAA_ENTERPRISE = "baa_enterprise"
    SOC2_TYPE2 = "soc2_type2"
    GDPR_STRICT = "gdpr_strict"


class ProviderComplianceTier(StrEnum):
    """Classification of LLM model providers based on executed legal and data agreements."""

    VERIFIED_BAA_SIGNED = "verified_baa_signed"
    PRIVATE_VLLM_AIRGAP = "private_vllm_airgap"
    UNVERIFIED_PUBLIC = "unverified_public"


@dataclass(frozen=True)
class BYOCompliantProvider:
    """Bring-Your-Own-Compliant-Provider registration record."""

    provider_id: str
    provider_name: str
    base_url: str
    tier: ProviderComplianceTier
    baa_agreement_id: str | None
    is_zero_training_mandated: bool = True
    permitted_models: tuple[str, ...] = ("gpt-4o", "claude-3-5-sonnet", "deepseek-v3")


@dataclass(frozen=True)
class HipaaAuditChainEntry:
    """Immutably hashed audit ledger entry recording lifecycle actions."""

    entry_id: str
    sequence_index: int
    event_type: str
    agent_id: str
    session_id: str
    timestamp: float
    action_summary: str
    phi_detected: bool
    prev_hash: str
    current_hash: str


@dataclass(frozen=True)
class PhiScreeningResult:
    """Outcome of Protected Health Information screening across inbound/outbound payloads."""

    is_clean: bool
    detected_phi_categories: tuple[str, ...]
    sanitized_content: str
    diagnostic: str


@dataclass(frozen=True)
class ComplianceExportPackage:
    """Comprehensive cryptographically verifiable compliance proof package."""

    export_id: str
    compliance_standard: ComplianceStandard
    generated_at: float
    total_events: int
    chain_valid: bool
    ledger_entries: tuple[HipaaAuditChainEntry, ...]
    summary_digest: str


@dataclass
class EnterpriseComplianceMetrics:
    """Operational telemetry counters for BAA/HIPAA compliance pipeline."""

    providers_registered_total: int = 0
    audit_events_recorded_total: int = 0
    phi_violations_blocked_total: int = 0
    unverified_egress_denied_total: int = 0
    compliance_exports_generated_total: int = 0
    zero_training_headers_injected_total: int = 0
