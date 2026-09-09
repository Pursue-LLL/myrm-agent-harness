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

    UNSUPPORTED_OS = "unsupported_os"
    """Operating system is not supported by skill contract."""

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

    optional: bool = False
    """Whether this dependency is optional."""


@dataclass(frozen=True, slots=True)
class PythonDependency:
    """Specification of a required Python package dependency."""

    package_name: str
    """PyPI package name (e.g. 'pdfplumber', 'pydub')."""

    version_constraint: str | None = None
    """PEP 440 version specifier (e.g. '>=0.10.0')."""

    import_name: str | None = None
    """Importable module name if different from package name."""


@dataclass(frozen=True, slots=True)
class SkillPrerequisites:
    """Full prerequisite declarations extracted from SKILL.md frontmatter or metadata."""

    supported_os: tuple[str, ...] = ("macos", "linux", "windows")
    """Supported operating systems."""

    binaries: tuple[BinaryDependency, ...] = ()
    """List of required OS binaries."""

    python_packages: tuple[PythonDependency, ...] = ()
    """List of required Python libraries."""

    env_vars: tuple[str, ...] = ()
    """Required environment variables."""

    def __init__(
        self,
        supported_os: tuple[str, ...] | list[str] | None = None,
        binaries: tuple[BinaryDependency, ...] | list[BinaryDependency] | None = None,
        python_packages: tuple[PythonDependency, ...] | list[PythonDependency] | None = None,
        env_vars: tuple[str, ...] | list[str] | None = None,
        *,
        os_compat: tuple[str, ...] | list[str] | None = None,
        packages: tuple[PythonDependency, ...] | list[PythonDependency] | None = None,
    ) -> None:
        effective_os = os_compat if os_compat is not None else (supported_os if supported_os is not None else ("macos", "linux", "windows"))
        effective_pkgs = packages if packages is not None else (python_packages if python_packages is not None else ())
        effective_bins = binaries if binaries is not None else ()
        effective_envs = env_vars if env_vars is not None else ()

        object.__setattr__(self, "supported_os", tuple(effective_os))
        object.__setattr__(self, "binaries", tuple(effective_bins))
        object.__setattr__(self, "python_packages", tuple(effective_pkgs))
        object.__setattr__(self, "env_vars", tuple(effective_envs))

    @property
    def os_compat(self) -> list[str]:
        return list(self.supported_os)

    @property
    def packages(self) -> list[PythonDependency]:
        return list(self.python_packages)

    @classmethod
    def from_manifest(cls, manifest: dict[str, Any]) -> SkillPrerequisites:
        """Parse prerequisites from generic manifest dict."""
        from .probe import parse_prerequisites_from_frontmatter

        return parse_prerequisites_from_frontmatter(manifest)

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

    @property
    def status(self) -> DependencyStatus:
        if not self.os_compatible:
            return DependencyStatus.UNSUPPORTED_OS
        return DependencyStatus.READY if self.is_ready else DependencyStatus.MISSING

    @property
    def missing_binaries(self) -> list[str]:
        return [it.name for it in self.items if it.dep_type == "binary" and it.status != DependencyStatus.READY]

    @property
    def missing_packages(self) -> list[str]:
        return [it.name for it in self.items if it.dep_type == "python" and it.status != DependencyStatus.READY]

    @property
    def remedy_commands(self) -> dict[str, str]:
        cmds: dict[str, str] = {}
        for it in self.items:
            if it.remediation_cmd:
                if it.dep_type == "binary":
                    cmds["system_install"] = it.remediation_cmd
                elif it.dep_type == "python":
                    cmds["python_install"] = it.remediation_cmd
        return cmds

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
