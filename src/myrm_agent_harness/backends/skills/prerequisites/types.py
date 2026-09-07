"""Type definitions and contracts for skill runtime prerequisites and system dependencies.

[INPUT]
- None

[OUTPUT]
- SkillPrerequisites, BinaryDependency, DependencyCheckItem, PrerequisiteCheckReport, PrerequisiteStatus

[POS]
Defines data structures for declaring and evaluating host environment prerequisites (CLI binaries, OS, Python packages).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


class PrerequisiteStatus(StrEnum):
    """Overall prerequisite readiness status."""

    READY = "ready"
    MISSING_REQUIRED = "missing_required"
    MISSING_OPTIONAL = "missing_optional"
    UNSUPPORTED_OS = "unsupported_os"


@dataclass(frozen=True, slots=True)
class BinaryDependency:
    """A system executable binary dependency."""

    name: str
    required: bool = True
    min_version: str | None = None
    description: str = ""
    package_names: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "required": self.required,
            "min_version": self.min_version,
            "description": self.description,
            "package_names": dict(self.package_names),
        }


@dataclass(frozen=True, slots=True)
class SkillPrerequisites:
    """Prerequisites contract declared by a skill."""

    supported_os: list[str] = field(default_factory=list)
    binaries: list[BinaryDependency] = field(default_factory=list)
    python_packages: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "supported_os": list(self.supported_os),
            "binaries": [b.to_dict() for b in self.binaries],
            "python_packages": list(self.python_packages),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SkillPrerequisites:
        if not data:
            return cls()

        raw_binaries = data.get("binaries", [])
        binaries: list[BinaryDependency] = []
        for item in raw_binaries:
            if isinstance(item, str):
                binaries.append(BinaryDependency(name=item, required=True))
            elif isinstance(item, dict):
                binaries.append(
                    BinaryDependency(
                        name=item.get("name", ""),
                        required=item.get("required", True),
                        min_version=item.get("min_version"),
                        description=item.get("description", ""),
                        package_names=item.get("package_names", {}),
                    )
                )

        return cls(
            supported_os=data.get("supported_os", []),
            binaries=binaries,
            python_packages=data.get("python_packages", []),
        )


@dataclass(frozen=True, slots=True)
class DependencyCheckItem:
    """Individual dependency check diagnostic item."""

    category: Literal["os", "binary", "python"]
    name: str
    satisfied: bool
    required: bool
    current_path: str | None = None
    current_version: str | None = None
    install_command: str | None = None
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "name": self.name,
            "satisfied": self.satisfied,
            "required": self.required,
            "current_path": self.current_path,
            "current_version": self.current_version,
            "install_command": self.install_command,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class PrerequisiteCheckReport:
    """Structured report returned after probing host environment for skill dependencies."""

    status: PrerequisiteStatus
    is_ready: bool
    items: list[DependencyCheckItem] = field(default_factory=list)
    remediation_commands: list[str] = field(default_factory=list)
    summary_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "is_ready": self.is_ready,
            "items": [item.to_dict() for item in self.items],
            "remediation_commands": list(self.remediation_commands),
            "summary_message": self.summary_message,
        }
