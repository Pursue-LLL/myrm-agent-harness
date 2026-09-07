"""Skill runtime prerequisites and system dependency checking toolkit.

[INPUT]
- models.py, probe.py, remediation.py

[OUTPUT]
- SkillPrerequisites, BinaryDependency, PythonDependency, DependencyCheckItem, PrerequisiteReport, DependencyStatus
- PrerequisiteProbe, check_skill_prerequisites, parse_prerequisites_from_frontmatter, generate_remediation_command

[POS]
Toolkit root exporting models, probes, and remediation generators.
"""

from __future__ import annotations

from .models import (
    BinaryDependency,
    DependencyCheckItem,
    DependencyStatus,
    PrerequisiteReport,
    PythonDependency,
    SkillPrerequisites,
)
from .probe import (
    PrerequisiteProbe,
    check_skill_prerequisites,
    parse_prerequisites_from_frontmatter,
)
from .probe import PrerequisiteProbe as HostPrerequisitesProbe
from .remediation import (
    detect_available_package_managers,
    generate_remediation_command,
    get_current_os,
)

__all__ = [
    "BinaryDependency",
    "DependencyCheckItem",
    "DependencyStatus",
    "HostPrerequisitesProbe",
    "PrerequisiteProbe",
    "PrerequisiteReport",
    "PythonDependency",
    "SkillPrerequisites",
    "check_skill_prerequisites",
    "detect_available_package_managers",
    "generate_remediation_command",
    "get_current_os",
    "parse_prerequisites_from_frontmatter",
]
