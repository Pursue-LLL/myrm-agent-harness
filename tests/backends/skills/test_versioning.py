"""Unit tests for skill versioning and upgrade guardrail."""

from __future__ import annotations

import pytest

from myrm_agent_harness.backends.skills.versioning import (
    SkillDowngradeBlockedError,
    VersionBumpType,
    classify_version_bump,
    compare_versions,
    validate_version_guard,
)


def test_compare_versions() -> None:
    delta = compare_versions("1.0.0", "1.1.0")
    assert delta.has_update is True

    delta_same = compare_versions("1.0.0", "1.0.0")
    assert delta_same.has_update is False

    delta_down = compare_versions("2.0.0", "1.0.0")
    assert delta_down.has_update is False


def test_classify_version_bump() -> None:
    assert classify_version_bump(None, "1.0.0") == VersionBumpType.INITIAL
    assert classify_version_bump("", "1.0.0") == VersionBumpType.INITIAL
    assert classify_version_bump("1.0.0", "1.0.0") == VersionBumpType.SAME
    assert classify_version_bump("1.0.0", "1.0.1") == VersionBumpType.PATCH
    assert classify_version_bump("1.0.0", "1.1.0") == VersionBumpType.MINOR
    assert classify_version_bump("1.0.0", "2.0.0") == VersionBumpType.MAJOR
    assert classify_version_bump("1.2.0", "1.1.0") == VersionBumpType.DOWNGRADE
    assert classify_version_bump("2.0.0", "1.9.9") == VersionBumpType.DOWNGRADE


def test_validate_version_guard_allowed_cases() -> None:
    # First install
    res = validate_version_guard(None, "1.0.0")
    assert res.allowed is True
    assert res.bump_type == VersionBumpType.INITIAL

    # Safe patch/minor/major bump
    res_patch = validate_version_guard("1.0.0", "1.0.1")
    assert res_patch.allowed is True
    assert res_patch.bump_type == VersionBumpType.PATCH

    res_minor = validate_version_guard("1.0.0", "1.2.0")
    assert res_minor.allowed is True
    assert res_minor.bump_type == VersionBumpType.MINOR

    res_major = validate_version_guard("1.0.0", "2.0.0")
    assert res_major.allowed is True
    assert res_major.bump_type == VersionBumpType.MAJOR
    assert "Major version upgrade" in res_major.reason


def test_validate_version_guard_downgrade_blocked() -> None:
    with pytest.raises(SkillDowngradeBlockedError) as exc_info:
        validate_version_guard("1.2.0", "1.0.0", allow_downgrade=False)

    assert exc_info.value.current_version == "1.2.0"
    assert exc_info.value.incoming_version == "1.0.0"
    assert exc_info.value.bump_type == VersionBumpType.DOWNGRADE
    assert "Skill downgrade blocked" in str(exc_info.value)


def test_validate_version_guard_downgrade_forced() -> None:
    res = validate_version_guard("1.2.0", "1.0.0", allow_downgrade=True)
    assert res.allowed is True
    assert res.bump_type == VersionBumpType.DOWNGRADE
    assert "Downgrade explicitly allowed" in res.reason
