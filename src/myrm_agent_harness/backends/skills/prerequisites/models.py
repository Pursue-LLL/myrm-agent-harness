"""Type definitions and data models for skill runtime prerequisites and system dependencies.

[INPUT]
- (none)

[OUTPUT]
- DependencyStatus, BinaryDependency, PythonDependency, SkillPrerequisites, DependencyCheckItem, PrerequisiteReport

[POS]
Type contracts shared across prerequisite probing, remediation recommendation, and frontend DTOs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


class DependencyStatus(StrEnum):
    """Evaluation status of a required prerequisite."""

    READY = "ready"
    """Dependency is installed and satisfies constraints."""

    MISSING = "missing"
    """Dependency executable or package is not found on host."""

    VERSION_MISMATCH = "version_mismatch"
    """Installed version does not satisfy the specified semver range."""

    UNKNOWN = "unknown"
    """Unable to verify dependency status."""


@dataclass(frozen=True, slots=True)
class BinaryDependency:
    """Specification of an OS-level executable binary prerequisite."""

    name: str
    """Primary executable name (e.g. 'ffmpeg', 'pandoc', 'pdftotext')."""

    min_version: str | None = None
    """Minimum required version string (e.g. '4.0.0')."""

    aliases: tuple[str, ...] = ()
    """Alternative binary names on various OS distributions (e.g. ('ffmpeg', 'avconv'))."""

    description: str = ""
    """Brief description of what this binary is used for."""

    package_names: dict[str, str] = field(default_factory=dict)
    """Package name mapping by manager: {'brew': 'ffmpeg', 'apt': 'ffmpeg', 'winget': 'Gyan.FFmpeg'}."""


@dataclass(frozen=True, slots=True)
class PythonDependency:
    """Specification of a required Python package dependency."""

    package_name: str
    """PyPI package name (e.g. 'pdfplumber', 'pydub')."""

    version_constraint: str | None = None
    """PEP 440 version specifier (e.g. '>=0.10.0')."""


@dataclass(frozen=True, slots=True)
class SkillPrerequisites:
    """Full prerequisite declarations extracted from SKILL.md frontmatter or metadata."""

    supported_os: tuple[Literal["macos", "linux", "windows"], ...] = ("macos", "linux", "windows")
    """Supported operating systems."""

    binaries: tuple[BinaryDependency, ...] = ()
    """List of required OS binaries."""

    python_packages: tuple[PythonDependency, ...] = ()
    """List of required Python libraries."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize prerequisites to dictionary."""
        return {
            "supported_os": list(self.supported_os),
            "binaries": [
                {
                    "name": b.name,
                    "min_version": b.min_version,
                    "aliases": list(b.aliases),
                    "description": b.description,
                    "package_names": b.package_names,
                }
                for b in self.binaries
            ],
            "python_packages": [
                {
                    "package_name": p.package_name,
                    "version_constraint": p.version_constraint,
                }
                for p in self.python_packages
            ],
        }


@dataclass(frozen=True, slots=True)
class DependencyCheckItem:
    """Status result for an individual evaluated dependency."""

    name: str
    dep_type: Literal["os", "binary", "python"]
    status: DependencyStatus
    detected_path: str | None = None
    detected_version: str | None = None
    remediation_cmd: str | None = None
    remediation_guide: str | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize check item to dictionary."""
        return {
            "name": self.name,
            "dep_type": self.dep_type,
            "status": self.status.value,
            "detected_path": self.detected_path,
            "detected_version": self.detected_version,
            "remediation_cmd": self.remediation_cmd,
            "remediation_guide": self.remediation_guide,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class PrerequisiteReport:
    """Consolidated report across all prerequisites of a skill."""

    skill_id: str
    is_ready: bool
    items: tuple[DependencyCheckItem, ...] = ()
    missing_count: int = 0
    os_compatible: bool = True
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize full report to dictionary."""
        return {
            "skill_id": self.skill_id,
            "is_ready": self.is_ready,
            "missing_count": self.missing_count,
            "os_compatible": self.os_compatible,
            "summary": self.summary,
            "items": [item.to_dict() for item in self.items],
        }
