"""Unit tests for Skill Engineering Governance and Privilege Verification suite.

[POS]
Harness core security test suite verifying skill contract parsing,
drift analysis with privilege escalation detection, and runtime mounting gating.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.skill_governance import (
    FilesystemScope,
    SkillEngineeringGovernanceGate,
    SkillPermissionContract,
    UnapprovedSkillMountError,
)


def test_parse_skill_contract_from_frontmatter() -> None:
    content = (
        "---\n"
        "tools:\n"
        "  - web_search\n"
        "  - bash\n"
        "network_egress: true\n"
        "filesystem_scope: full_access\n"
        "---\n"
        "# System Admin Skill\n"
        "Automates server provisioning.\n"
    )

    contract = SkillEngineeringGovernanceGate.parse_skill_contract(
        content=content,
        skill_name="sysadmin",
        version="1.0.0",
    )

    assert contract.skill_name == "sysadmin"
    assert contract.version == "1.0.0"
    assert "web_search" in contract.declared_tools
    assert "bash" in contract.declared_tools
    assert contract.network_egress is True
    assert contract.filesystem_scope == FilesystemScope.FULL_ACCESS
    assert contract.requires_admin_review is True


def test_diff_skill_contracts_detects_escalation() -> None:
    base = SkillPermissionContract(
        skill_name="data_summarizer",
        version="1.0.0",
        declared_tools=frozenset({"web_search"}),
        network_egress=False,
        filesystem_scope=FilesystemScope.TASK_WORKSPACE,
        requires_admin_review=False,
    )

    # Version 1.1.0 sneakily introduces bash and full_access
    target = SkillPermissionContract(
        skill_name="data_summarizer",
        version="1.1.0",
        declared_tools=frozenset({"web_search", "bash"}),
        network_egress=True,
        filesystem_scope=FilesystemScope.FULL_ACCESS,
        requires_admin_review=True,
    )

    diff = SkillEngineeringGovernanceGate.diff_skill_contracts(base, target)

    assert diff.skill_name == "data_summarizer"
    assert diff.base_version == "1.0.0"
    assert diff.target_version == "1.1.0"
    assert "bash" in diff.added_tools
    assert diff.has_privilege_escalation is True
    assert diff.review_required is True

    escalated = set(diff.escalated_permissions)
    assert "added_high_risk_tool:bash" in escalated
    assert "escalated_network_egress" in escalated
    assert "escalated_filesystem_full_access" in escalated


def test_validate_runtime_mounting_enforcement() -> None:
    elevated_contract = SkillPermissionContract(
        skill_name="deployer",
        version="2.0.0",
        declared_tools=frozenset({"bash_code_execute"}),
        network_egress=True,
        filesystem_scope=FilesystemScope.FULL_ACCESS,
        requires_admin_review=True,
    )

    # 1. Mounting elevated contract without approval raises UnapprovedSkillMountError
    with pytest.raises(UnapprovedSkillMountError):
        SkillEngineeringGovernanceGate.validate_runtime_mounting(
            contract=elevated_contract,
            is_approved=False,
        )

    # 2. Approved elevated contract succeeds
    assert (
        SkillEngineeringGovernanceGate.validate_runtime_mounting(
            contract=elevated_contract,
            is_approved=True,
        )
        is True
    )

    # 3. Benign contract succeeds without prior approval
    benign_contract = SkillPermissionContract(
        skill_name="word_counter",
        version="1.0.0",
        declared_tools=frozenset({"clarify"}),
        network_egress=False,
        filesystem_scope=FilesystemScope.READ_ONLY,
        requires_admin_review=False,
    )
    assert (
        SkillEngineeringGovernanceGate.validate_runtime_mounting(
            contract=benign_contract,
            is_approved=False,
        )
        is True
    )
