"""Host environment prerequisite probing engine and remediation command generator.

[INPUT]
- types.py

[OUTPUT]
- HostPrerequisiteProbe, evaluate_skill_prerequisites

[POS]
Lightweight, non-blocking environment scanner that inspects CLI binaries, Python modules, and generates OS-specific package manager install commands.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import shutil
import sys
from typing import Any, Literal

from .types import (
    BinaryDependency,
    DependencyCheckItem,
    PrerequisiteCheckReport,
    PrerequisiteStatus,
    SkillPrerequisites,
)

logger = logging.getLogger(__name__)

# Common CLI binary to package manager name mappings
DEFAULT_BINARY_PKG_MAP: dict[str, dict[Literal["darwin", "linux", "win32"], str]] = {
    "ffmpeg": {"darwin": "ffmpeg", "linux": "ffmpeg", "win32": "ffmpeg"},
    "pandoc": {"darwin": "pandoc", "linux": "pandoc", "win32": "JohnMacFarlane.Pandoc"},
    "pdftotext": {"darwin": "poppler", "linux": "poppler-utils", "win32": "poppler"},
    "pdfimages": {"darwin": "poppler", "linux": "poppler-utils", "win32": "poppler"},
    "tesseract": {"darwin": "tesseract", "linux": "tesseract-ocr", "win32": "UB-Mannheim.TesseractOCR"},
    "git": {"darwin": "git", "linux": "git", "win32": "Git.Git"},
    "docker": {"darwin": "docker", "linux": "docker.io", "win32": "Docker.DockerDesktop"},
    "graphviz": {"darwin": "graphviz", "linux": "graphviz", "win32": "Graphviz.Graphviz"},
    "tree": {"darwin": "tree", "linux": "tree", "win32": "tree"},
    "jq": {"darwin": "jq", "linux": "jq", "win32": "jqlang.jq"},
}


class HostPrerequisiteProbe:
    """Probes the host operating system, binary PATH, and Python environment."""

    def __init__(self, custom_binary_map: dict[str, dict[str, str]] | None = None) -> None:
        self._binary_pkg_map = dict(DEFAULT_BINARY_PKG_MAP)
        if custom_binary_map:
            for k, v in custom_binary_map.items():
                self._binary_pkg_map[k] = v  # type: ignore

    @property
    def current_os(self) -> Literal["darwin", "linux", "win32"]:
        if sys.platform == "darwin":
            return "darwin"
        elif sys.platform.startswith("linux"):
            return "linux"
        return "win32"

    def check_binary(self, dep: BinaryDependency) -> DependencyCheckItem:
        """Check if an executable binary is present in system PATH."""
        bin_path = shutil.which(dep.name)
        satisfied = bin_path is not None

        install_cmd = None
        if not satisfied:
            install_cmd = self._generate_binary_install_command(dep)

        return DependencyCheckItem(
            category="binary",
            name=dep.name,
            satisfied=satisfied,
            required=dep.required,
            current_path=bin_path,
            install_command=install_cmd,
            description=dep.description,
        )

    def check_python_package(self, package_name: str) -> DependencyCheckItem:
        """Check if a Python package or module is importable."""
        # Normalize package name (e.g. 'beautifulsoup4' -> 'bs4' or direct check)
        mod_name = package_name.replace("-", "_").split("==")[0].split(">=")[0].split("<=")[0]
        try:
            spec = importlib.util.find_spec(mod_name)
            satisfied = spec is not None
        except Exception:
            satisfied = False

        install_cmd = None if satisfied else f"pip install {package_name}"

        return DependencyCheckItem(
            category="python",
            name=package_name,
            satisfied=satisfied,
            required=True,
            install_command=install_cmd,
            description=f"Python module '{package_name}'",
        )

    def _generate_binary_install_command(self, dep: BinaryDependency) -> str:
        """Generate platform-specific installation command (Homebrew / Apt / Winget)."""
        os_key = self.current_os
        pkg_name = dep.package_names.get(os_key) or self._binary_pkg_map.get(dep.name, {}).get(os_key, dep.name)

        if os_key == "darwin":
            return f"brew install {pkg_name}"
        elif os_key == "linux":
            return f"sudo apt-get install -y {pkg_name}"
        else:
            return f"winget install {pkg_name}"

    def evaluate(self, prerequisites: SkillPrerequisites) -> PrerequisiteCheckReport:
        """Evaluate full prerequisites contract against current host system."""
        items: list[DependencyCheckItem] = []
        os_key = self.current_os

        # 1. OS Compatibility Check
        if prerequisites.supported_os:
            os_supported = os_key in prerequisites.supported_os
            items.append(
                DependencyCheckItem(
                    category="os",
                    name=os_key,
                    satisfied=os_supported,
                    required=True,
                    description=f"Operating system support: {', '.join(prerequisites.supported_os)}",
                )
            )
            if not os_supported:
                return PrerequisiteCheckReport(
                    status=PrerequisiteStatus.UNSUPPORTED_OS,
                    is_ready=False,
                    items=items,
                    remediation_commands=[],
                    summary_message=f"Current OS '{os_key}' is not supported by this skill (requires {', '.join(prerequisites.supported_os)}).",
                )

        # 2. Binary Dependencies Check
        missing_required_bin = False
        missing_optional_bin = False
        remediation_cmds: list[str] = []

        for dep in prerequisites.binaries:
            item = self.check_binary(dep)
            items.append(item)
            if not item.satisfied:
                if item.required:
                    missing_required_bin = True
                else:
                    missing_optional_bin = True
                if item.install_command:
                    remediation_cmds.append(item.install_command)

        # 3. Python Package Dependencies Check
        missing_py = False
        for py_pkg in prerequisites.python_packages:
            item = self.check_python_package(py_pkg)
            items.append(item)
            if not item.satisfied:
                missing_py = True
                if item.install_command:
                    remediation_cmds.append(item.install_command)

        # Determine overall status
        if missing_required_bin or missing_py:
            status = PrerequisiteStatus.MISSING_REQUIRED
            is_ready = False
            summary = "Required system dependencies or Python packages are missing."
        elif missing_optional_bin:
            status = PrerequisiteStatus.MISSING_OPTIONAL
            is_ready = True  # Ready to run with core functionality
            summary = "All required dependencies are satisfied; some optional tools are missing."
        else:
            status = PrerequisiteStatus.READY
            is_ready = True
            summary = "All runtime prerequisites and system dependencies are ready."

        return PrerequisiteCheckReport(
            status=status,
            is_ready=is_ready,
            items=items,
            remediation_commands=remediation_cmds,
            summary_message=summary,
        )


def evaluate_skill_prerequisites(prerequisites: SkillPrerequisites | dict[str, Any] | None) -> PrerequisiteCheckReport:
    """Convenience helper to evaluate prerequisites against host probe."""
    if isinstance(prerequisites, dict):
        prerequisites = SkillPrerequisites.from_dict(prerequisites)
    elif prerequisites is None:
        prerequisites = SkillPrerequisites()

    probe = HostPrerequisiteProbe()
    return probe.evaluate(prerequisites)
