"""
[POS] src/myrm_agent_harness/core/security/target_scope_boundary/egress_boundary_interceptor.py
[INPUT] ipaddress, logging, typing, .types, .scope_contract_validator
[OUTPUT] DynamicEgressBoundaryInterceptor

Dynamic egress boundary interceptor and emergency kill-switch manager.
Performs pre-flight destination verification, DNS IP resolution inspection,
and zero-trust enforcement of Rules of Engagement (ROE) boundaries.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import ipaddress
import logging

from .scope_contract_validator import TargetScopeContractValidator
from .types import (
    ScopeVerdict,
    ScopeVerificationResult,
    TargetScopeContract,
)

logger = logging.getLogger(__name__)


class DynamicEgressBoundaryInterceptor:
    """Intercepts outbound network calls from sandbox security tools and enforces ROE scope boundaries."""

    def __init__(
        self,
        validator: TargetScopeContractValidator | None = None,
        initial_contract: TargetScopeContract | None = None,
    ) -> None:
        self._validator = validator or TargetScopeContractValidator()
        self._active_contract = initial_contract
        self._is_kill_switch_active = False

    def set_active_contract(self, contract: TargetScopeContract | None) -> None:
        """Configure the active Rules of Engagement scope contract."""
        self._active_contract = contract
        if contract:
            logger.info(
                "Active target scope contract set: '%s' (engagement: %s).",
                contract.contract_id,
                contract.engagement_name,
            )
        else:
            logger.info("Active target scope contract cleared.")

    def get_active_contract(self) -> TargetScopeContract | None:
        """Retrieve the currently active ROE contract."""
        return self._active_contract

    def activate_emergency_kill_switch(self) -> None:
        """Activate emergency kill-switch, instantly severing all outbound traffic."""
        self._is_kill_switch_active = True
        logger.critical("EMERGENCY KILL-SWITCH ACTIVATED: All outbound scanner egress is completely severed.")

    def reset_emergency_kill_switch(self) -> None:
        """Reset emergency kill-switch to resume authorized scoped scans."""
        self._is_kill_switch_active = False
        logger.info("Emergency kill-switch reset: Outbound traffic subject to standard ROE evaluation.")

    def is_kill_switch_active(self) -> bool:
        """Check if emergency kill-switch is currently engaged."""
        return self._is_kill_switch_active

    def verify_egress_target(
        self,
        target_host: str,
        resolved_ip: str | None = None,
    ) -> ScopeVerificationResult:
        """Verify destination host and resolved IP against active ROE contract and kill-switch."""
        cleaned_host = target_host.strip()
        contract = self._active_contract

        # 1. Emergency Kill-Switch Check
        if self._is_kill_switch_active:
            msg = "Outbound egress blocked: Emergency kill-switch is currently active."
            logger.warning(msg)
            return ScopeVerificationResult(
                is_allowed=False,
                verdict=ScopeVerdict.EMERGENCY_KILL_SWITCH_ACTIVE,
                target_host=cleaned_host,
                resolved_ip=resolved_ip,
                diagnostic_reason=msg,
                contract_id=contract.contract_id if contract else None,
            )

        # 2. Cloud Metadata Defense Check (host or resolved IP)
        if self._validator.is_cloud_metadata(cleaned_host) or (
            resolved_ip and self._validator.is_cloud_metadata(resolved_ip)
        ):
            msg = f"Outbound call to cloud provider metadata endpoint '{cleaned_host}' is strictly forbidden."
            logger.error("Cloud metadata violation: %s", msg)
            return ScopeVerificationResult(
                is_allowed=False,
                verdict=ScopeVerdict.CLOUD_METADATA_PROHIBITED,
                target_host=cleaned_host,
                resolved_ip=resolved_ip,
                diagnostic_reason=msg,
                contract_id=contract.contract_id if contract else None,
            )

        # 3. Active Contract Existence Check
        if contract is None or not contract.is_active:
            msg = "Outbound call blocked: No active ROE target scope contract configured."
            logger.warning(msg)
            return ScopeVerificationResult(
                is_allowed=False,
                verdict=ScopeVerdict.OUT_OF_SCOPE_BLOCKED,
                target_host=cleaned_host,
                resolved_ip=resolved_ip,
                diagnostic_reason=msg,
                contract_id=None,
            )

        # 4. Determine if target_host is a direct IP or Domain Name
        is_direct_ip = False
        try:
            ipaddress.ip_address(cleaned_host)
            is_direct_ip = True
        except ValueError:
            is_direct_ip = False

        if is_direct_ip:
            if not self._validator.is_ip_in_scope(cleaned_host, contract):
                msg = f"Direct IP destination '{cleaned_host}' is outside authorized CIDR scope."
                logger.warning(msg)
                return ScopeVerificationResult(
                    is_allowed=False,
                    verdict=ScopeVerdict.UNAUTHORIZED_IP_BLOCKED,
                    target_host=cleaned_host,
                    resolved_ip=cleaned_host,
                    diagnostic_reason=msg,
                    contract_id=contract.contract_id,
                )
        else:
            # Domain Name Scope Evaluation
            if not self._validator.is_domain_in_scope(cleaned_host, contract):
                msg = f"Target domain '{cleaned_host}' is outside authorized ROE domain scope."
                logger.warning(msg)
                return ScopeVerificationResult(
                    is_allowed=False,
                    verdict=ScopeVerdict.OUT_OF_SCOPE_BLOCKED,
                    target_host=cleaned_host,
                    resolved_ip=resolved_ip,
                    diagnostic_reason=msg,
                    contract_id=contract.contract_id,
                )

            # Secondary DNS IP Scope Verification
            if resolved_ip and not self._validator.is_ip_in_scope(resolved_ip, contract):
                msg = (
                    f"Target domain '{cleaned_host}' resolved to IP '{resolved_ip}', "
                    f"which is outside authorized CIDRs."
                )
                logger.warning(msg)
                return ScopeVerificationResult(
                    is_allowed=False,
                    verdict=ScopeVerdict.UNAUTHORIZED_IP_BLOCKED,
                    target_host=cleaned_host,
                    resolved_ip=resolved_ip,
                    diagnostic_reason=msg,
                    contract_id=contract.contract_id,
                )

        # Successfully authorized destination
        return ScopeVerificationResult(
            is_allowed=True,
            verdict=ScopeVerdict.IN_SCOPE_ALLOWED,
            target_host=cleaned_host,
            resolved_ip=resolved_ip,
            diagnostic_reason="Target destination satisfies all ROE scope constraints.",
            contract_id=contract.contract_id,
        )
