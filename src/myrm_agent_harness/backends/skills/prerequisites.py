"""Skill runtime prerequisites contract and host system dependency probe.

[INPUT]
- typing, dataclasses, shutil, sys, os

[OUTPUT]
- SkillPrerequisitesContract: Data model representing requirements (platforms, binaries, python_packages, env_vars)
- HostPrerequisitesProbe: Probe checking binary existence and OS platform compatibility
- PrerequisitesCheckResult: Complete diagnostics report with per-platform remediation command hints

[POS]
myrm_agent_harness.backends.skills.prerequisites
Enables pre-install and pre-run system dependency verification to prevent 'command not found' errors.
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Canonical package manager install recipes for common skill binaries
COMMON_BINARY_PACKAGES: dict[str, dict[str, str]] = {
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
    "graphviz": {
        "macos": "brew install graphviz",
        "linux": "sudo apt-get update && sudo apt-get install -y graphviz",
        "windows": "winget install SoftwareEntwicklerSoftwareGmbH.Graphviz",
    },
    "tesseract": {
        "macos": "brew install tesseract",
        "linux": "sudo apt-get update && sudo apt-get install -y tesseract-ocr",
        "windows": "winget install UB-Mannheim.TesseractOCR",
    },
    "git": {
        "macos": "brew install git",
        "linux": "sudo apt-get update && sudo apt-get install -y git",
        "windows": "winget install Git.Git",
    },
    "curl": {
        "macos": "brew install curl",
        "linux": "sudo apt-get update && sudo apt-get install -y curl",
        "windows": "winget install cURL.cURL",
    },
    "jq": {
        "macos": "brew install jq",
        "linux": "sudo apt-get update && sudo apt-get install -y jq",
        "windows": "winget install jqlang.jq",
    },
    "imagemagick": {
        "macos": "brew install imagemagick",
        "linux": "sudo apt-get update && sudo apt-get install -y imagemagick",
        "windows": "winget install ImageMagick.ImageMagick",
    },
}


@dataclass(frozen=True, slots=True)
class SkillPrerequisitesContract:
    """Declared prerequisite requirements for a skill."""

    platforms: tuple[str, ...] = field(default_factory=tuple)
    """Supported operating systems: 'macos', 'linux', 'windows'."""

    binaries: tuple[str, ...] = field(default_factory=tuple)
    """Required host CLI executables (e.g. 'ffmpeg', 'pandoc')."""

    python_packages: tuple[str, ...] = field(default_factory=tuple)
    """Required Python packages (e.g. 'requests', 'pillow')."""

    env_vars: tuple[str, ...] = field(default_factory=tuple)
    """Required environment variables (e.g. 'OPENAI_API_KEY')."""

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> SkillPrerequisitesContract:
        """Parse from raw dictionary."""
        if not data:
            return cls()

        platforms_raw = data.get("platforms") or data.get("platform") or ()
        if isinstance(platforms_raw, str):
            platforms_raw = [p.strip().lower() for p in platforms_raw.split(",") if p.strip()]
        elif isinstance(platforms_raw, (list, tuple)):
            platforms_raw = [str(p).strip().lower() for p in platforms_raw if str(p).strip()]
        else:
            platforms_raw = ()

        binaries_raw = data.get("binaries") or data.get("dependencies") or ()
        if isinstance(binaries_raw, str):
            binaries_raw = [b.strip() for b in binaries_raw.split(",") if b.strip()]
        elif isinstance(binaries_raw, (list, tuple)):
            binaries_raw = [str(b).strip() for b in binaries_raw if str(b).strip()]
        else:
            binaries_raw = ()

        python_raw = data.get("python_packages") or data.get("python") or ()
        if isinstance(python_raw, str):
            python_raw = [p.strip() for p in python_raw.split(",") if p.strip()]
        elif isinstance(python_raw, (list, tuple)):
            python_raw = [str(p).strip() for p in python_raw if str(p).strip()]
        else:
            python_raw = ()

        env_raw = data.get("env_vars") or data.get("env") or ()
        if isinstance(env_raw, str):
            env_raw = [e.strip() for e in env_raw.split(",") if e.strip()]
        elif isinstance(env_raw, (list, tuple)):
            env_raw = [str(e).strip() for e in env_raw if str(e).strip()]
        else:
            env_raw = ()

        return cls(
            platforms=tuple(platforms_raw),
            binaries=tuple(binaries_raw),
            python_packages=tuple(python_raw),
            env_vars=tuple(env_raw),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize contract to dict."""
        return {
            "platforms": list(self.platforms),
            "binaries": list(self.binaries),
            "python_packages": list(self.python_packages),
            "env_vars": list(self.env_vars),
        }


@dataclass(frozen=True, slots=True)
class PrerequisitesCheckResult:
    """Result of probing host system against skill prerequisites."""

    is_ready: bool
    platform_supported: bool
    current_platform: str
    missing_binaries: tuple[str, ...] = field(default_factory=tuple)
    installed_binaries: tuple[str, ...] = field(default_factory=tuple)
    missing_env_vars: tuple[str, ...] = field(default_factory=tuple)
    remediation_commands: dict[str, str] = field(default_factory=dict)
    summary_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize check result to dictionary for API/UI."""
        return {
            "is_ready": self.is_ready,
            "platform_supported": self.platform_supported,
            "current_platform": self.current_platform,
            "missing_binaries": list(self.missing_binaries),
            "installed_binaries": list(self.installed_binaries),
            "missing_env_vars": list(self.missing_env_vars),
            "remediation_commands": self.remediation_commands,
            "summary_message": self.summary_message,
        }


class HostPrerequisitesProbe:
    """Host environment probe for system binary and platform prerequisites."""

    @staticmethod
    def get_current_platform() -> str:
        """Resolve current OS platform name in canonical form: 'macos', 'linux', 'windows'."""
        if sys.platform == "darwin":
            return "macos"
        if sys.platform.startswith("linux"):
            return "linux"
        if sys.platform in ("win32", "cygwin"):
            return "windows"
        return sys.platform.lower()

    @classmethod
    def check_binary_installed(cls, binary_name: str) -> bool:
        """Check if executable exists in PATH."""
        return shutil.which(binary_name) is not None

    @classmethod
    def check_prerequisites(
        cls,
        contract: SkillPrerequisitesContract,
    ) -> PrerequisitesCheckResult:
        """Evaluate contract against host environment."""
        cur_platform = cls.get_current_platform()

        # 1. Platform check
        platform_ok = True
        if contract.platforms:
            canonical_supported = {p.lower() for p in contract.platforms}
            # Allow 'darwin' as alias for 'macos', 'win' for 'windows'
            if "darwin" in canonical_supported:
                canonical_supported.add("macos")
            if "win" in canonical_supported:
                canonical_supported.add("windows")
            platform_ok = cur_platform in canonical_supported

        # 2. Binaries check
        missing_bins: list[str] = []
        installed_bins: list[str] = []
        for b in contract.binaries:
            if cls.check_binary_installed(b):
                installed_bins.append(b)
            else:
                missing_bins.append(b)

        # 3. Environment variables check
        missing_envs: list[str] = []
        for env_name in contract.env_vars:
            if not os.getenv(env_name):
                missing_envs.append(env_name)

        # 4. Generate remediation commands
        remediation_cmds = cls._generate_remediation_commands(missing_bins, cur_platform)

        is_ready = platform_ok and len(missing_bins) == 0 and len(missing_envs) == 0

        # Construct summary message
        if is_ready:
            msg = "All prerequisites satisfied."
        else:
            parts = []
            if not platform_ok:
                parts.append(
                    f"Unsupported OS '{cur_platform}' (requires: {', '.join(contract.platforms)})"
                )
            if missing_bins:
                parts.append(f"Missing system CLI tools: {', '.join(missing_bins)}")
            if missing_envs:
                parts.append(f"Missing environment variables: {', '.join(missing_envs)}")
            msg = "; ".join(parts)

        return PrerequisitesCheckResult(
            is_ready=is_ready,
            platform_supported=platform_ok,
            current_platform=cur_platform,
            missing_binaries=tuple(missing_bins),
            installed_binaries=tuple(installed_bins),
            missing_env_vars=tuple(missing_envs),
            remediation_commands=remediation_cmds,
            summary_message=msg,
        )

    @staticmethod
    def _generate_remediation_commands(
        missing_binaries: list[str],
        current_platform: str,
    ) -> dict[str, str]:
        """Generate platform-specific install commands for missing dependencies."""
        if not missing_binaries:
            return {}

        commands: dict[str, str] = {}
        macos_pkgs: list[str] = []
        linux_pkgs: list[str] = []
        win_pkgs: list[str] = []

        for b in missing_binaries:
            recipe = COMMON_BINARY_PACKAGES.get(b.lower())
            if recipe:
                if "brew" in recipe.get("macos", ""):
                    macos_pkgs.append(recipe["macos"].replace("brew install ", ""))
                if "apt" in recipe.get("linux", ""):
                    linux_pkgs.append(
                        recipe["linux"].split("install -y ")[-1]
                        if "install -y " in recipe["linux"]
                        else b
                    )
                if "winget" in recipe.get("windows", ""):
                    win_pkgs.append(recipe["windows"].replace("winget install ", ""))
            else:
                # Fallback to binary name directly
                macos_pkgs.append(b)
                linux_pkgs.append(b)
                win_pkgs.append(b)

        if macos_pkgs:
            commands["macos"] = f"brew install {' '.join(macos_pkgs)}"
        if linux_pkgs:
            commands["linux"] = f"sudo apt-get update && sudo apt-get install -y {' '.join(linux_pkgs)}"
        if win_pkgs:
            commands["windows"] = f"winget install {' '.join(win_pkgs)}"

        return commands
