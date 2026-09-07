"""Unit tests for Skill Runtime Prerequisites and Host Dependency Check Suite.

[INPUT]
- myrm_agent_harness.backends.skills.dependency_checker

[OUTPUT]
- pytest suite for SkillPrerequisiteContract, HostPrerequisiteProbe, and RemediationEngine

[POS]
myrm-agent-harness/tests/backends/skills/test_dependency_checker.py
"""

from unittest.mock import patch
import pytest

from myrm_agent_harness.backends.skills.dependency_checker import (
    HostPrerequisiteProbe,
    RemediationEngine,
    SkillPrerequisiteContract,
    SkillPrerequisiteReport,
)


def test_contract_from_dict_parsing() -> None:
    data = {
        "os": ["macos", "linux"],
        "binaries": ["ffmpeg", "pandoc"],
        "python_packages": ["pydantic", "pillow"],
    }
    contract = SkillPrerequisiteContract.from_dict(data)
    assert contract.os == ["macos", "linux"]
    assert contract.binaries == ["ffmpeg", "pandoc"]
    assert contract.python_packages == ["pydantic", "pillow"]

    # Test alias mappings
    alias_data = {
        "platforms": "windows",
        "system_binaries": "git",
        "packages": "pytest",
    }
    alias_contract = SkillPrerequisiteContract.from_dict(alias_data)
    assert alias_contract.os == ["windows"]
    assert alias_contract.binaries == ["git"]
    assert alias_contract.python_packages == ["pytest"]


def test_remediation_engine_generates_commands() -> None:
    remediations = RemediationEngine.generate_remediation_commands(
        missing_binaries=["ffmpeg", "pandoc"],
        missing_python_packages=["pillow"],
        target_os="macos",
    )
    assert "macos" in remediations
    assert "linux" in remediations
    assert "windows" in remediations

    assert "brew install ffmpeg" in remediations["macos"]
    assert "brew install pandoc" in remediations["macos"]
    assert "uv pip install pillow" in remediations["macos"]

    assert "sudo apt-get install -y ffmpeg" in remediations["linux"]
    assert "winget install JohnMacFarlane.Pandoc" in remediations["windows"]


def test_probe_evaluation_all_satisfied() -> None:
    contract = SkillPrerequisiteContract(
        os=["macos", "linux", "windows"],
        binaries=["python3"],
        python_packages=["json"],
    )

    with patch.object(HostPrerequisiteProbe, "get_current_os", return_value="macos"), \
         patch.object(HostPrerequisiteProbe, "check_binary_available", return_value=True), \
         patch.object(HostPrerequisiteProbe, "check_python_package_available", return_value=True):
        report = HostPrerequisiteProbe.evaluate(contract)
        assert report.is_satisfied is True
        assert report.supported_os is True
        assert len(report.missing_binaries) == 0
        assert len(report.missing_python_packages) == 0
        assert "All system prerequisites and dependencies are satisfied" in report.diagnostic_message


def test_probe_evaluation_missing_binary_and_os_mismatch() -> None:
    contract = SkillPrerequisiteContract(
        os=["windows"],
        binaries=["nonexistent_bin_12345"],
        python_packages=["nonexistent_pkg_xyz"],
    )

    with patch.object(HostPrerequisiteProbe, "get_current_os", return_value="macos"), \
         patch.object(HostPrerequisiteProbe, "check_binary_available", return_value=False), \
         patch.object(HostPrerequisiteProbe, "check_python_package_available", return_value=False):
        report = HostPrerequisiteProbe.evaluate(contract)
        assert report.is_satisfied is False
        assert report.supported_os is False
        assert "nonexistent_bin_12345" in report.missing_binaries
        assert "nonexistent_pkg_xyz" in report.missing_python_packages
        assert "Operating system 'macos' not in supported list" in report.diagnostic_message
