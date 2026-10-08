"""Enterprise role-based permission template presets and compliance drift evaluation.

[POS] src/myrm_agent_harness/core/security/managed_permission_rollback/template_presets.py
[INPUT] myrm_agent_harness.core.security.managed_permission_rollback.types
[OUTPUT] EnterprisePermissionPresetRegistry
"""

from __future__ import annotations

import logging
from typing import Final

from myrm_agent_harness.core.security.managed_permission_rollback.types import (
    ComplianceDriftItem,
    ComplianceDriftReport,
    EnterpriseRoleTemplate,
    PermissionActionRule,
    RolePermissionPolicy,
)

logger: Final[logging.Logger] = logging.getLogger(__name__)


class EnterprisePermissionPresetRegistry:
    """Registry maintaining canonical enterprise permission templates and evaluating drift."""

    def __init__(self) -> None:
        self._presets: dict[EnterpriseRoleTemplate, RolePermissionPolicy] = self._build_canonical_presets()

    def get_preset(self, role: EnterpriseRoleTemplate) -> RolePermissionPolicy:
        """Fetch canonical permission policy definition for the specified role."""
        return self._presets[role]

    def list_presets(self) -> list[RolePermissionPolicy]:
        """Return all available canonical enterprise permission templates."""
        return list(self._presets.values())

    def evaluate_compliance_drift(
        self,
        agent_id: str,
        assigned_role: EnterpriseRoleTemplate,
        active_rules: dict[str, PermissionActionRule],
        active_allow_shell: bool,
    ) -> ComplianceDriftReport:
        """Compare an agent's active privileges against its designated template baseline."""
        template = self.get_preset(assigned_role)
        deviations: list[ComplianceDriftItem] = []

        # 1. Check rule-level divergences
        for dim, template_rule in template.rules.items():
            actual_rule = active_rules.get(dim)
            if actual_rule is None:
                continue

            if actual_rule != template_rule:
                is_excessive = self._is_rule_more_permissive(actual_rule, template_rule)
                hint = (
                    f"Reset {dim} from {actual_rule.value} to {template_rule.value}"
                    if is_excessive
                    else f"Template allows {template_rule.value}, currently tightened to {actual_rule.value}"
                )
                deviations.append(
                    ComplianceDriftItem(
                        target=dim,
                        template_rule=template_rule.value,
                        actual_rule=actual_rule.value,
                        is_excessive=is_excessive,
                        remediation_hint=hint,
                    )
                )

        # 2. Check shell execution boundary
        if active_allow_shell and not template.allow_shell_execution:
            deviations.append(
                ComplianceDriftItem(
                    target="SHELL_EXECUTION",
                    template_rule="PROHIBITED",
                    actual_rule="ENABLED",
                    is_excessive=True,
                    remediation_hint="Disable shell execution to comply with role policy.",
                )
            )

        excessive_count = sum(1 for d in deviations if d.is_excessive)
        drift_score = min(1.0, (excessive_count * 0.3) + (len(deviations) * 0.1))
        is_compliant = excessive_count == 0

        logger.info(
            "Compliance drift evaluated for agent=%s role=%s: compliant=%s, deviations=%d",
            agent_id,
            assigned_role.value,
            is_compliant,
            len(deviations),
        )

        return ComplianceDriftReport(
            agent_id=agent_id,
            assigned_role=assigned_role,
            is_compliant=is_compliant,
            drift_score=round(drift_score, 2),
            deviations=deviations,
        )

    @staticmethod
    def _is_rule_more_permissive(
        actual: PermissionActionRule, baseline: PermissionActionRule
    ) -> bool:
        """Determine if actual rule confers broader privileges than baseline."""
        weight_map = {
            PermissionActionRule.DENY: 0,
            PermissionActionRule.ASK_HUMAN: 1,
            PermissionActionRule.ALWAYS_ALLOW: 2,
        }
        return weight_map[actual] > weight_map[baseline]

    @staticmethod
    def _build_canonical_presets() -> dict[EnterpriseRoleTemplate, RolePermissionPolicy]:
        """Construct the 4 core canonical enterprise role policies."""
        return {
            EnterpriseRoleTemplate.AUDITOR: RolePermissionPolicy(
                role=EnterpriseRoleTemplate.AUDITOR,
                display_name="Auditor (Read-Only Compliance)",
                description="Strict read-only analysis without network egress or shell mutations.",
                rules={
                    "TOOLS": PermissionActionRule.DENY,
                    "FILES": PermissionActionRule.ALWAYS_ALLOW,  # read allowed in sandbox
                    "APIS": PermissionActionRule.DENY,
                    "SENDS": PermissionActionRule.DENY,
                },
                max_network_egress_domains=0,
                allow_shell_execution=False,
                require_hitl_on_external_sends=True,
                allowed_filesystem_roots=["/workspace/reports"],
            ),
            EnterpriseRoleTemplate.SAFE_COLLABORATOR: RolePermissionPolicy(
                role=EnterpriseRoleTemplate.SAFE_COLLABORATOR,
                display_name="Safe Collaborator (Standard Assistant)",
                description="Conversational and document drafting assistant with human-in-the-loop gates.",
                rules={
                    "TOOLS": PermissionActionRule.ASK_HUMAN,
                    "FILES": PermissionActionRule.ALWAYS_ALLOW,
                    "APIS": PermissionActionRule.ASK_HUMAN,
                    "SENDS": PermissionActionRule.ASK_HUMAN,
                },
                max_network_egress_domains=3,
                allow_shell_execution=False,
                require_hitl_on_external_sends=True,
                allowed_filesystem_roots=["/workspace"],
            ),
            EnterpriseRoleTemplate.FULL_STACK_DEVELOPER: RolePermissionPolicy(
                role=EnterpriseRoleTemplate.FULL_STACK_DEVELOPER,
                display_name="Full-Stack Developer (Autonomous Sandbox Coding)",
                description="High-velocity local coding and testing within sandbox; gates on external credentials.",
                rules={
                    "TOOLS": PermissionActionRule.ALWAYS_ALLOW,
                    "FILES": PermissionActionRule.ALWAYS_ALLOW,
                    "APIS": PermissionActionRule.ASK_HUMAN,
                    "SENDS": PermissionActionRule.ASK_HUMAN,
                },
                max_network_egress_domains=10,
                allow_shell_execution=True,
                require_hitl_on_external_sends=True,
                allowed_filesystem_roots=["/workspace", "/tmp/build"],
            ),
            EnterpriseRoleTemplate.AUTONOMOUS_OPS: RolePermissionPolicy(
                role=EnterpriseRoleTemplate.AUTONOMOUS_OPS,
                display_name="Autonomous Ops (Infrastructure Operator)",
                description="Automated operations across verified endpoints; strict deny on bottom-line destructions.",
                rules={
                    "TOOLS": PermissionActionRule.ALWAYS_ALLOW,
                    "FILES": PermissionActionRule.ALWAYS_ALLOW,
                    "APIS": PermissionActionRule.ALWAYS_ALLOW,
                    "SENDS": PermissionActionRule.ASK_HUMAN,
                },
                max_network_egress_domains=50,
                allow_shell_execution=True,
                require_hitl_on_external_sends=False,
                allowed_filesystem_roots=["/workspace", "/var/log", "/etc/config"],
            ),
        }
