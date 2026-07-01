"""Architecture gate: backends.skills.types aggregate re-export integrity."""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.architecture
def test_skill_types_all_exports_are_importable() -> None:
    """Every name in types.__all__ must resolve on the public aggregate module."""
    types_mod = importlib.import_module("myrm_agent_harness.backends.skills.types")
    for name in types_mod.__all__:
        assert hasattr(types_mod, name), f"Missing skill types export: {name}"


@pytest.mark.architecture
def test_skill_types_all_matches_public_surface() -> None:
    """__all__ must list exactly the supported public skill type symbols."""
    types_mod = importlib.import_module("myrm_agent_harness.backends.skills.types")
    expected = {
        "MCPSkillData",
        "SecurityFindingDetail",
        "SecurityScanSummary",
        "SkillContract",
        "SkillContractJudgment",
        "SkillContractTrap",
        "SkillContractVerification",
        "SkillInstance",
        "SkillInstanceConfig",
        "SkillLifecycleStatus",
        "SkillMetadata",
        "SkillPermission",
        "SkillRequires",
        "SkillStateProtocol",
        "SkillTrust",
        "SkillUsageStats",
        "skill_visible_for_tools",
    }
    assert set(types_mod.__all__) == expected
