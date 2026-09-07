"""Unit tests for Skill Runtime Prerequisites and System Dependency Checker.

[INPUT]
- myrm_agent_harness.backends.skills.dependency_checker

[OUTPUT]
- pytest suite covering OS platform filtering, binary checks, Python package resolution, and remediation generation

[POS]
myrm-agent-harness/tests/backends/skills/test_dependency_checker.py
"""

from unittest.mock import patch
import pytest

from myrm_agent_harness.backends.skills.dependency_checker import (
    HostPrerequisiteProbe,
    RemediationEngine,
    SkillPrerequisiteContract,
)


def test_prerequisite_contract_parsing() -> None:
    raw_data = {
        "os": ["macos", "linux"],
        "binaries": ["ffmpeg", "pandoc"],
        "python_packages": ["pillow", "pydantic"],
    }
    contract = SkillPrerequisiteContract.from_dict(raw_data)
    assert contract.os == ["macos", "linux"]
    assert contract.binaries == ["ffmpeg", "pandoc"]
    assert contract.python_packages == ["pillow", "pydantic"]


def test_host_prerequisite_probe_satisfied() -> None:
    contract = SkillPrerequisiteContract(
        os=["macos", "linux", "windows"],
        binaries=["python3"],
        python_packages=["json"],
    )

    with patch.object(HostPrerequisiteProbe, "get_current_os", return_value="macos"):
        with patch.object(HostPrerequisiteProbe, "check_binary_available", return_value=True):
            with patch.object(
                HostPrerequisiteProbe, "check_python_package_available", return_value=True
            ):
                report = HostPrerequisiteProbe.evaluate(contract)
                assert report.is_satisfied is True
                assert report.supported_os is True
                assert len(report.missing_binaries) == 0
                assert len(report.missing_python_packages) == 0


def test_host_prerequisite_probe_missing_dependencies() -> None:
    contract = SkillPrerequisiteContract(
        os=["macos"],
        binaries=["nonexistent_cli_bin", "ffmpeg"],
        python_packages=["nonexistent_python_pkg"],
    )

    with patch.object(HostPrerequisiteProbe, "get_current_os", return_value="macos"):
        def mock_binary(name: str) -> bool:
            return name == "ffmpeg"

        def mock_pkg(name: str) -> bool:
            return False

        with patch.object(HostPrerequisiteProbe, "check_binary_available", side_effect=mock_binary):
            with patch.object(
                HostPrerequisiteProbe, "check_python_package_available", side_effect=mock_pkg
            ):
                report = HostPrerequisiteProbe.evaluate(contract)
                assert report.is_satisfied is False
                assert report.missing_binaries == ["nonexistent_cli_bin"]
                assert report.missing_python_packages == ["nonexistent_python_pkg"]
                assert "macos" in report.remediation_commands
                assert "brew install nonexistent_cli_bin" in report.remediation_commands["macos"]
                assert "uv pip install nonexistent_python_pkg" in report.remediation_commands["macos"]


def test_remediation_engine_known_packages() -> None:
    remediation = RemediationEngine.generate_remediation_commands(
        missing_binaries=["ffmpeg", "pandoc"],
        missing_python_packages=[],
        target_os="macos",
    )
    assert "brew install ffmpeg && brew install pandoc" in remediation["macos"]
    assert "sudo apt-get update && sudo apt-get install -y ffmpeg && sudo apt-get update && sudo apt-get install -y pandoc" in remediation["linux"]
    assert "winget install Gyan.FFmpeg && winget install JohnMacFarlane.Pandoc" in remediation["windows"]


def test_host_prerequisite_probe_unsupported_os() -> None:
    contract = SkillPrerequisiteContract(
        os=["linux"],
        binaries=[],
        python_packages=[],
    )
    with patch.object(HostPrerequisiteProbe, "get_current_os", return_value="macos"):
        report = HostPrerequisiteProbe.evaluate(contract)
        assert report.is_satisfied is False
        assert report.supported_os is False
        assert "not in supported list" in report.diagnostic_message


def test_empty_contract_evaluation() -> None:
    contract = SkillPrerequisiteContract.from_dict(None)
    report = HostPrerequisiteProbe.evaluate(contract)
    assert report.is_satisfied is True
    assert report.supported_os is True
    assert len(report.missing_binaries) == 0
    assert len(report.missing_python_packages) == 0

