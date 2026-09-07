"""Skill runtime prerequisites and system host dependency checker.

[INPUT]
- typing, shutil, importlib, sys, pathlib

[OUTPUT]
- SkillPrerequisiteContract, SkillPrerequisiteReport, HostPrerequisiteProbe, RemediationEngine

[POS]
myrm_agent_harness.backends.skills.dependency_checker
Sniffs host CLI binary dependencies (ffmpeg, pandoc, etc.), OS platform compatibility,
and Python packages before skill execution or after installation to guarantee out-of-the-box reliability.
"""

from __future__ import annotations

import importlib.util
import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SkillPrerequisiteContract:
    """Declared prerequisite requirements for a skill."""

    os: list[str] = field(default_factory=list)
    """Supported OS list: ['macos', 'linux', 'windows'] (empty means all supported)."""

    binaries: list[str] = field(default_factory=list)
    """Required system executable names on PATH (e.g. ['ffmpeg', 'pandoc', 'pdftotext'])."""

    python_packages: list[str] = field(default_factory=list)
    """Required Python package names importable in current runtime."""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SkillPrerequisiteContract:
        if not data or not isinstance(data, dict):
            return cls()

        raw_os = data.get("os") or data.get("platforms") or []
        if isinstance(raw_os, str):
            raw_os = [raw_os]

        raw_bin = data.get("binaries") or data.get("system_binaries") or data.get("bins") or []
        if isinstance(raw_bin, str):
            raw_bin = [raw_bin]

        raw_py = (
            data.get("python_packages")
            or data.get("packages")
            or data.get("python")
            or []
        )
        if isinstance(raw_py, str):
            raw_py = [raw_py]

        return cls(
            os=[str(item).lower().strip() for item in raw_os if item],
            binaries=[str(item).strip() for item in raw_bin if item],
            python_packages=[str(item).strip() for item in raw_py if item],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "os": list(self.os),
            "binaries": list(self.binaries),
            "python_packages": list(self.python_packages),
        }


@dataclass(frozen=True, slots=True)
class SkillPrerequisiteReport:
    """Inspection report detailing prerequisite satisfaction and remediation guidance."""

    is_satisfied: bool
    """True if all OS, binary, and Python package requirements are met."""

    supported_os: bool
    """True if current OS matches declared OS constraints."""

    current_os: str
    """Current host OS identifier ('macos', 'linux', 'windows', or 'unknown')."""

    missing_binaries: list[str] = field(default_factory=list)
    """List of required CLI binaries missing from system PATH."""

    missing_python_packages: list[str] = field(default_factory=list)
    """List of required Python packages missing in current environment."""

    remediation_commands: dict[str, str] = field(default_factory=dict)
    """Platform-specific installation commands (e.g. {'macos': 'brew install ffmpeg'})."""

    diagnostic_message: str = ""
    """Human-readable summary of the prerequisite status."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_satisfied": self.is_satisfied,
            "supported_os": self.supported_os,
            "current_os": self.current_os,
            "missing_binaries": list(self.missing_binaries),
            "missing_python_packages": list(self.missing_python_packages),
            "remediation_commands": dict(self.remediation_commands),
            "diagnostic_message": self.diagnostic_message,
        }


class RemediationEngine:
    """Generates cross-platform remediation commands for missing CLI tools and Python packages."""

    # Well-known package manager binary mappings
    PACKAGE_MAP: dict[str, dict[str, str]] = {
        "ffmpeg": {
            "macos": "brew install ffmpeg",
            "linux": "sudo apt-get update && sudo apt-get install -y ffmpeg",
            "windows": "winget install Gyan.FFmpeg",
        },
        "pandoc": {
            "macos": "brew install pandoc",
            "linux": "sudo apt-get update && sudo apt-get install -y pandoc",
            "windows": "winget install JohnMacFarlane.Pandoc",
        },
        "pdftotext": {
            "macos": "brew install poppler",
            "linux": "sudo apt-get update && sudo apt-get install -y poppler-utils",
            "windows": "winget install poppler",
        },
        "tesseract": {
            "macos": "brew install tesseract",
            "linux": "sudo apt-get update && sudo apt-get install -y tesseract-ocr",
            "windows": "winget install UB-Mannheim.TesseractOCR",
        },
        "graphviz": {
            "macos": "brew install graphviz",
            "linux": "sudo apt-get update && sudo apt-get install -y graphviz",
            "windows": "winget install Graphviz.Graphviz",
        },
        "docker": {
            "macos": "brew install --cask docker",
            "linux": "sudo apt-get update && sudo apt-get install -y docker.io",
            "windows": "winget install Docker.DockerDesktop",
        },
        "kubectl": {
            "macos": "brew install kubectl",
            "linux": "sudo apt-get update && sudo apt-get install -y kubectl",
            "windows": "winget install Kubernetes.kubectl",
        },
    }

    @classmethod
    def generate_remediation_commands(
        cls,
        missing_binaries: list[str],
        missing_python_packages: list[str],
        target_os: str,
    ) -> dict[str, str]:
        """Generate copyable command lines for missing dependencies on target OS."""
        remediations: dict[str, str] = {}
        all_platforms = ["macos", "linux", "windows"]

        for plat in all_platforms:
            bin_cmds: list[str] = []
            for b in missing_binaries:
                if b in cls.PACKAGE_MAP and plat in cls.PACKAGE_MAP[b]:
                    bin_cmds.append(cls.PACKAGE_MAP[b][plat])
                else:
                    if plat == "macos":
                        bin_cmds.append(f"brew install {b}")
                    elif plat == "linux":
                        bin_cmds.append(f"sudo apt-get install -y {b}")
                    else:
                        bin_cmds.append(f"winget install {b}")

            py_cmds: list[str] = []
            if missing_python_packages:
                joined_pkgs = " ".join(missing_python_packages)
                py_cmds.append(f"uv pip install {joined_pkgs}")

            full_cmds = bin_cmds + py_cmds
            if full_cmds:
                remediations[plat] = " && ".join(full_cmds)

        return remediations


class HostPrerequisiteProbe:
    """Sniffs system environment and validates skill prerequisite contracts."""

    @staticmethod
    def get_current_os() -> str:
        """Return standardized OS string: 'macos', 'linux', 'windows', or 'unknown'."""
        if sys.platform == "darwin":
            return "macos"
        elif sys.platform.startswith("linux"):
            return "linux"
        elif sys.platform in ("win32", "cygwin"):
            return "windows"
        return "unknown"

    @classmethod
    def check_binary_available(cls, binary_name: str) -> bool:
        """Check if an executable binary is present on PATH."""
        if not binary_name:
            return True
        return shutil.which(binary_name) is not None

    @classmethod
    def check_python_package_available(cls, package_name: str) -> bool:
        """Check if a Python package is importable in the current environment."""
        if not package_name:
            return True
        # Normalize package name (e.g., 'pillow' -> 'PIL')
        normalized = package_name.lower().replace("-", "_")
        module_name = "PIL" if normalized == "pillow" else normalized

        try:
            return importlib.util.find_spec(module_name) is not None
        except Exception:
            return False

    @classmethod
    def evaluate(cls, contract: SkillPrerequisiteContract) -> SkillPrerequisiteReport:
        """Evaluate a skill prerequisite contract against current host environment."""
        cur_os = cls.get_current_os()

        # 1. OS check
        supported_os = True
        if contract.os:
            normalized_os_list = [o.lower().strip() for o in contract.os]
            if cur_os != "unknown" and cur_os not in normalized_os_list:
                supported_os = False

        # 2. Binary dependencies
        missing_binaries = [b for b in contract.binaries if not cls.check_binary_available(b)]

        # 3. Python package dependencies
        missing_python = [
            p for p in contract.python_packages if not cls.check_python_package_available(p)
        ]

        is_satisfied = (
            supported_os
            and len(missing_binaries) == 0
            and len(missing_python) == 0
        )

        remediation = RemediationEngine.generate_remediation_commands(
            missing_binaries,
            missing_python,
            cur_os,
        )

        # Build diagnostic message
        if is_satisfied:
            msg = "All system prerequisites and dependencies are satisfied."
        else:
            issues: list[str] = []
            if not supported_os:
                issues.append(f"Operating system '{cur_os}' not in supported list ({', '.join(contract.os)})")
            if missing_binaries:
                issues.append(f"Missing system binaries: {', '.join(missing_binaries)}")
            if missing_python:
                issues.append(f"Missing Python packages: {', '.join(missing_python)}")
            msg = "Prerequisites missing: " + "; ".join(issues)

        return SkillPrerequisiteReport(
            is_satisfied=is_satisfied,
            supported_os=supported_os,
            current_os=cur_os,
            missing_binaries=missing_binaries,
            missing_python_packages=missing_python,
            remediation_commands=remediation,
            diagnostic_message=msg,
        )
