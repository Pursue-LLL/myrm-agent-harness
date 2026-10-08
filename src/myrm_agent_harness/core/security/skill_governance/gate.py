"""Skill Engineering Governance Gate and Permission Contract Inspector.

[INPUT]
- SKILL.md content, SkillPermissionContract models, approval flags.

[OUTPUT]
- SkillPermissionContract parsed from frontmatter or declarations.
- SkillDriftAnalysis tracking privilege mutations between versions.
- Validation verdict permitting or blocking runtime mounting.

[POS]
- Harness core security module inspired by Mike Julian engineering SecOps governance.
- Enforces strict contracts over Agent Skills, blocking silent privilege escalation.
"""

from __future__ import annotations

import re

import yaml

from myrm_agent_harness.core.security.skill_governance.types import (
    FilesystemScope,
    SkillDriftAnalysis,
    SkillPermissionContract,
    UnapprovedSkillMountError,
)

_HIGH_RISK_TOOLS = frozenset({
    "bash",
    "bash_code_execute",
    "terminal_spawn",
    "subprocess",
    "shell_exec",
    "db_mutate",
    "file_delete",
})

_FRONTMATTER_REGEX = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class SkillEngineeringGovernanceGate:
    """Gatekeeper enforcing permission contracts, drift detection, and mounting authorization."""

    @classmethod
    def parse_skill_contract(
        cls,
        content: str,
        skill_name: str,
        version: str = "1.0.0",
    ) -> SkillPermissionContract:
        """Parse frontmatter or markup from SKILL.md to build a strong permission contract."""
        frontmatter_data: dict[str, object] = {}
        match = _FRONTMATTER_REGEX.search(content)
        if match:
            raw_yaml = match.group(1)
            try:
                parsed = yaml.safe_load(raw_yaml)
                if isinstance(parsed, dict):
                    frontmatter_data = parsed
            except Exception:
                frontmatter_data = {}

        # 1. Extract tools
        tools_raw = frontmatter_data.get("tools") or frontmatter_data.get("required_tools")
        declared_tools: set[str] = set()
        if isinstance(tools_raw, list):
            for t in tools_raw:
                if isinstance(t, str):
                    declared_tools.add(t.strip().lower())
        elif isinstance(tools_raw, str):
            declared_tools.add(tools_raw.strip().lower())

        # Also scan body for tool usages if not declared in frontmatter
        if not declared_tools:
            if "bash" in content.lower():
                declared_tools.add("bash")
            if "web_search" in content.lower():
                declared_tools.add("web_search")

        # 2. Extract network egress
        net_raw = frontmatter_data.get("network_egress")
        if isinstance(net_raw, bool):
            network_egress = net_raw
        else:
            network_egress = bool(re.search(r"\b(https?://|curl|requests|fetch)\b", content, re.IGNORECASE))

        # 3. Extract filesystem scope
        fs_raw = str(frontmatter_data.get("filesystem_scope", "")).lower().strip()
        if fs_raw == "read_only":
            fs_scope = FilesystemScope.READ_ONLY
        elif fs_raw == "full_access":
            fs_scope = FilesystemScope.FULL_ACCESS
        else:
            fs_scope = FilesystemScope.TASK_WORKSPACE

        # Determine if admin review is required
        has_high_risk_tool = any(t in _HIGH_RISK_TOOLS for t in declared_tools)
        requires_review = (
            has_high_risk_tool
            or network_egress
            or fs_scope == FilesystemScope.FULL_ACCESS
        )

        return SkillPermissionContract(
            skill_name=skill_name,
            version=version,
            declared_tools=frozenset(declared_tools),
            network_egress=network_egress,
            filesystem_scope=fs_scope,
            requires_admin_review=requires_review,
        )

    @classmethod
    def diff_skill_contracts(
        cls,
        base: SkillPermissionContract | None,
        target: SkillPermissionContract,
    ) -> SkillDriftAnalysis:
        """Analyze difference between baseline contract and target contract, flagging escalations."""
        findings: list[str] = []
        escalated_perms: list[str] = []

        if base is None:
            # Initial contract registration
            findings.append(f"Initial registration for skill '{target.skill_name}' (v{target.version}).")
            if target.requires_admin_review:
                findings.append("Skill requests elevated permissions requiring initial security sign-off.")
            return SkillDriftAnalysis(
                skill_name=target.skill_name,
                base_version=None,
                target_version=target.version,
                added_tools=target.declared_tools,
                removed_tools=frozenset(),
                escalated_permissions=tuple(target.declared_tools if target.requires_admin_review else ()),
                has_privilege_escalation=target.requires_admin_review,
                review_required=target.requires_admin_review,
                audit_findings=tuple(findings),
            )

        # Comparative analysis
        added_tools = target.declared_tools - base.declared_tools
        removed_tools = base.declared_tools - target.declared_tools

        # 1. Check added tools
        for tool in added_tools:
            if tool in _HIGH_RISK_TOOLS:
                escalated_perms.append(f"added_high_risk_tool:{tool}")
                findings.append(f"Privilege escalation: newly added high-risk tool '{tool}'.")
            else:
                findings.append(f"Added standard tool '{tool}'.")

        # 2. Check network egress escalation
        if not base.network_egress and target.network_egress:
            escalated_perms.append("escalated_network_egress")
            findings.append("Privilege escalation: network egress enabled in target version.")

        # 3. Check filesystem scope escalation
        if base.filesystem_scope != FilesystemScope.FULL_ACCESS and target.filesystem_scope == FilesystemScope.FULL_ACCESS:
            escalated_perms.append("escalated_filesystem_full_access")
            findings.append("Privilege escalation: filesystem scope elevated to 'full_access'.")

        has_escalation = len(escalated_perms) > 0
        review_required = has_escalation or (target.requires_admin_review and not base.requires_admin_review)

        return SkillDriftAnalysis(
            skill_name=target.skill_name,
            base_version=base.version,
            target_version=target.version,
            added_tools=frozenset(added_tools),
            removed_tools=frozenset(removed_tools),
            escalated_permissions=tuple(escalated_perms),
            has_privilege_escalation=has_escalation,
            review_required=review_required,
            audit_findings=tuple(findings),
        )

    @classmethod
    def validate_runtime_mounting(
        cls,
        contract: SkillPermissionContract,
        is_approved: bool,
    ) -> bool:
        """Validate whether a skill contract satisfies runtime security gates before mounting.

        Raises:
            UnapprovedSkillMountError: If elevated skill lacks human security approval.
        """
        if contract.requires_admin_review and not is_approved:
            raise UnapprovedSkillMountError(
                f"Mounting blocked for skill '{contract.skill_name}' (v{contract.version}): "
                "Skill declares elevated capabilities (shell, egress, or full filesystem) "
                "and lacks mandatory administrator approval."
            )
        return True
