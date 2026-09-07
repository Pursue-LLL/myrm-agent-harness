"""Unit tests for Skill Runtime Prerequisites and System Dependency Check Suite.

[INPUT]
- myrm_agent_harness.backends.skills.prerequisites

[OUTPUT]
- pytest suite covering OS compatibility, binary check, package inspection, and remedy generation

[POS]
myrm-agent-harness/tests/backends/skills/prerequisites/test_prerequisites_probe.py
"""

from unittest.mock import MagicMock, patch
import pytest

from myrm_agent_harness.backends.skills.prerequisites import (
    AutoRemedyGenerator,
    BinaryRequirement,
    HostPrerequisiteProbe,
    PackageRequirement,
    PrerequisiteStatus,
    SkillPrerequisites,
    probe_skill_prerequisites,
)


def test_prerequisites_from_manifest_parsing() -> None:
    manifest = {
        "os": ["macos", "linux"],
        "binaries": ["ffmpeg", {"name": "pandoc", "optional": True}],
        "packages": ["httpx", {"name": "pandas", "import_name": "pandas"}],
        "env_vars": ["OPENAI_API_KEY"],
    }
    prereqs = SkillPrerequisites.from_manifest(manifest)
    assert prereqs.os_compat == ["macos", "linux"]
    assert len(prereqs.binaries) == 2
    assert prereqs.binaries[0].name == "ffmpeg"
    assert prereqs.binaries[1].optional is True
    assert len(prereqs.packages) == 2
    assert prereqs.env_vars == ["OPENAI_API_KEY"]


def test_probe_satisfied_prerequisites() -> None:
    prereqs = SkillPrerequisites(
        os_compat=["macos", "linux", "windows"],
        binaries=[BinaryRequirement(name="python3")],
        packages=[PackageRequirement(package_name="pytest")],
        env_vars=[],
    )

    probe = HostPrerequisiteProbe()
    with patch.object(probe, "is_binary_available", return_value=True), patch.object(
        probe, "is_package_available", return_value=True
    ):
        report = probe.check(prereqs)
        assert report.status == PrerequisiteStatus.READY
        assert report.is_ready is True
        assert report.missing_binaries == []
        assert report.missing_packages == []


def test_probe_missing_binaries_generates_remedy() -> None:
    prereqs = SkillPrerequisites(
        os_compat=["macos"],
        binaries=[BinaryRequirement(name="ffmpeg")],
        packages=[PackageRequirement(package_name="opencv-python")],
        env_vars=[],
    )

    probe = HostPrerequisiteProbe()
    with patch.object(probe, "current_os", return_value="macos"), patch.object(
        probe, "is_binary_available", return_value=False
    ), patch.object(probe, "is_package_available", return_value=False):
        report = probe.check(prereqs)
        assert report.status == PrerequisiteStatus.MISSING
        assert report.is_ready is False
        assert report.missing_binaries == ["ffmpeg"]
        assert report.missing_packages == ["opencv-python"]
        assert "brew install ffmpeg" in report.remedy_commands.get("system_install", "")
        assert "uv pip install opencv-python" in report.remedy_commands.get("python_install", "")


def test_probe_unsupported_os() -> None:
    prereqs = SkillPrerequisites(os_compat=["windows"])
    probe = HostPrerequisiteProbe()
    with patch.object(probe, "current_os", return_value="macos"):
        report = probe.check(prereqs)
        assert report.status == PrerequisiteStatus.UNSUPPORTED_OS
        assert report.is_ready is False
        assert "Skill requires OS (windows)" in report.summary


def test_auto_remedy_generator_cross_platform() -> None:
    gen = AutoRemedyGenerator()
    remedies_mac = gen.generate_remedies(["ffmpeg", "pandoc"], ["numpy"], target_os="macos")
    assert "brew install ffmpeg && brew install pandoc" in remedies_mac["system_install"]
    assert "uv pip install numpy" in remedies_mac["python_install"]

    remedies_win = gen.generate_remedies(["ffmpeg"], [], target_os="windows")
    assert "winget install Gyan.FFmpeg" in remedies_win["system_install"]
