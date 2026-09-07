"""Host prerequisite and system dependency probe engine.

[INPUT]
- models.py, remediation.py

[OUTPUT]
- PrerequisiteProbe, check_skill_prerequisites, parse_prerequisites_from_frontmatter

[POS]
Lightweight, non-blocking asynchronous probe inspecting binary presence, OS compatibility, and Python packages.
"""

from __future__ import annotations

import importlib.util
import logging
import re
import shutil
from typing import Any

from .models import (
    BinaryDependency,
    DependencyCheckItem,
    DependencyStatus,
    PrerequisiteReport,
    PythonDependency,
    SkillPrerequisites,
)
from .remediation import generate_remediation_command, get_current_os

logger = logging.getLogger(__name__)


class PrerequisiteProbe:
    """Probes host environment against skill prerequisite contracts."""

    def __init__(self) -> None:
        self.current_os = get_current_os()

    def check_binary(self, dep: BinaryDependency) -> DependencyCheckItem:
        """Probe for executable binary presence in system PATH."""
        candidates = [dep.name, *dep.aliases]
        detected_path: str | None = None

        for name in candidates:
            path = shutil.which(name)
            if path:
                detected_path = path
                break

        if not detected_path:
            remediation_cmd = generate_remediation_command(dep)
            return DependencyCheckItem(
                name=dep.name,
                dep_type="binary",
                status=DependencyStatus.MISSING,
                remediation_cmd=remediation_cmd,
                message=f"Executable binary '{dep.name}' not found in system PATH.",
            )

        return DependencyCheckItem(
            name=dep.name,
            dep_type="binary",
            status=DependencyStatus.READY,
            detected_path=detected_path,
            message=f"Binary ready at {detected_path}",
        )

    def check_python_package(self, dep: PythonDependency) -> DependencyCheckItem:
        """Probe for Python library availability."""
        spec = importlib.util.find_spec(dep.package_name)
        if spec is None:
            return DependencyCheckItem(
                name=dep.package_name,
                dep_type="python",
                status=DependencyStatus.MISSING,
                remediation_cmd=f"pip install '{dep.package_name}'",
                message=f"Python package '{dep.package_name}' is not installed.",
            )

        return DependencyCheckItem(
            name=dep.package_name,
            dep_type="python",
            status=DependencyStatus.READY,
            message=f"Python package '{dep.package_name}' is installed.",
        )

    def evaluate(self, skill_id: str, prereqs: SkillPrerequisites) -> PrerequisiteReport:
        """Evaluate full prerequisites contract for a skill."""
        items: list[DependencyCheckItem] = []
        os_compatible = self.current_os in prereqs.supported_os

        if not os_compatible:
            items.append(
                DependencyCheckItem(
                    name=f"OS: {self.current_os}",
                    dep_type="os",
                    status=DependencyStatus.MISSING,
                    message=f"Skill requires {prereqs.supported_os}, but host is {self.current_os}.",
                )
            )

        for b in prereqs.binaries:
            items.append(self.check_binary(b))

        for p in prereqs.python_packages:
            items.append(self.check_python_package(p))

        missing_items = [it for it in items if it.status != DependencyStatus.READY]
        is_ready = len(missing_items) == 0 and os_compatible

        if is_ready:
            summary = "All system prerequisites and binary dependencies are satisfied."
        else:
            missing_names = ", ".join(it.name for it in missing_items)
            summary = f"Missing prerequisites: {missing_names}"

        return PrerequisiteReport(
            skill_id=skill_id,
            is_ready=is_ready,
            items=tuple(items),
            missing_count=len(missing_items),
            os_compatible=os_compatible,
            summary=summary,
        )


def parse_prerequisites_from_frontmatter(metadata: dict[str, Any]) -> SkillPrerequisites:
    """Parse structured prerequisites from frontmatter YAML dictionary."""
    supported_os: list[str] = metadata.get("supported_os", ["macos", "linux", "windows"])
    binaries: list[BinaryDependency] = []
    python_packages: list[PythonDependency] = []

    # Parse binaries
    raw_binaries = metadata.get("binaries") or metadata.get("dependencies", {}).get("binaries", [])
    if isinstance(raw_binaries, list):
        for b in raw_binaries:
            if isinstance(b, str):
                binaries.append(BinaryDependency(name=b))
            elif isinstance(b, dict) and "name" in b:
                binaries.append(
                    BinaryDependency(
                        name=b["name"],
                        min_version=b.get("min_version"),
                        aliases=tuple(b.get("aliases", ())),
                        description=b.get("description", ""),
                        package_names=b.get("package_names", {}),
                    )
                )

    # Parse python packages
    raw_python = metadata.get("python_packages") or metadata.get("dependencies", {}).get(
        "python", []
    )
    if isinstance(raw_python, list):
        for p in raw_python:
            if isinstance(p, str):
                python_packages.append(PythonDependency(package_name=p))
            elif isinstance(p, dict) and "package_name" in p:
                python_packages.append(
                    PythonDependency(
                        package_name=p["package_name"],
                        version_constraint=p.get("version_constraint"),
                    )
                )

    return SkillPrerequisites(
        supported_os=tuple(supported_os),
        binaries=tuple(binaries),
        python_packages=tuple(python_packages),
    )


def check_skill_prerequisites(
    skill_id: str,
    metadata: dict[str, Any] | SkillPrerequisites,
) -> PrerequisiteReport:
    """Convenience functional entry for checking prerequisites."""
    probe = PrerequisiteProbe()
    if isinstance(metadata, SkillPrerequisites):
        prereqs = metadata
    else:
        prereqs = parse_prerequisites_from_frontmatter(metadata)
    return probe.evaluate(skill_id, prereqs)
