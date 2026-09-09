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
from .models import BinaryDependency as BinaryRequirement
from .models import DependencyStatus as PrerequisiteStatus
from .models import PythonDependency as PackageRequirement
from .probe import (
    PrerequisiteProbe,
    check_skill_prerequisites,
    parse_prerequisites_from_frontmatter,
)
from .probe import PrerequisiteProbe as HostPrerequisitesProbe
from .probe import PrerequisiteProbe as HostPrerequisiteProbe
from .probe import check_skill_prerequisites as probe_skill_prerequisites
from .remediation import (
    detect_available_package_managers,
    generate_remediation_command,
    get_current_os,
)
from .remedy import AutoRemedyGenerator

__all__ = [
    "AutoRemedyGenerator",
    "BinaryDependency",
    "BinaryRequirement",
    "DependencyCheckItem",
    "DependencyStatus",
    "HostPrerequisiteProbe",
    "HostPrerequisitesProbe",
    "PackageRequirement",
    "PrerequisiteProbe",
    "PrerequisiteReport",
    "PrerequisiteStatus",
    "PythonDependency",
    "SkillPrerequisites",
    "check_skill_prerequisites",
    "detect_available_package_managers",
    "generate_remediation_command",
    "get_current_os",
    "parse_prerequisites_from_frontmatter",
    "probe_skill_prerequisites",
]
