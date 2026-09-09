"""Remediation and package manager installation command generator.

[INPUT]
- models.py

[OUTPUT]
- get_current_os, detect_package_managers, generate_remediation_command

[POS]
Generates system-aware one-click installation commands across macOS (brew), Linux (apt/pacman/dnf), and Windows (winget/choco).
"""

from __future__ import annotations

import os
import platform
import shutil
from typing import Literal

from .models import BinaryDependency

COMMON_BINARY_PACKAGES: dict[str, dict[str, str]] = {
    "ffmpeg": {
        "brew": "brew install ffmpeg",
        "apt": "sudo apt-get install -y ffmpeg",
        "pacman": "sudo pacman -S ffmpeg",
        "dnf": "sudo dnf install -y ffmpeg",
        "winget": "winget install Gyan.FFmpeg",
        "choco": "choco install ffmpeg",
    },
    "pandoc": {
        "brew": "brew install pandoc",
        "apt": "sudo apt-get install -y pandoc",
        "pacman": "sudo pacman -S pandoc-cli",
        "dnf": "sudo dnf install -y pandoc",
        "winget": "winget install JohnMacFarlane.Pandoc",
        "choco": "choco install pandoc",
    },
    "pdftotext": {
        "brew": "brew install poppler",
        "apt": "sudo apt-get install -y poppler-utils",
        "pacman": "sudo pacman -S poppler",
        "dnf": "sudo dnf install -y poppler-utils",
        "winget": "winget install poppler",
        "choco": "choco install poppler",
    },
    "graphviz": {
        "brew": "brew install graphviz",
        "apt": "sudo apt-get install -y graphviz",
        "pacman": "sudo pacman -S graphviz",
        "dnf": "sudo dnf install -y graphviz",
        "winget": "winget install Graphviz.Graphviz",
        "choco": "choco install graphviz",
    },
    "tesseract": {
        "brew": "brew install tesseract",
        "apt": "sudo apt-get install -y tesseract-ocr",
        "pacman": "sudo pacman -S tesseract",
        "dnf": "sudo dnf install -y tesseract",
        "winget": "winget install UB-Mannheim.TesseractOCR",
        "choco": "choco install tesseract",
    },
}


def get_current_os() -> Literal["macos", "linux", "windows"]:
    """Identify the current host operating system."""
    sys_name = platform.system().lower()
    if "darwin" in sys_name:
        return "macos"
    if "windows" in sys_name:
        return "windows"
    return "linux"


def detect_available_package_managers() -> list[str]:
    """Detect package managers available in host PATH."""
    mgrs: list[str] = []
    current_os = get_current_os()

    if current_os == "macos":
        if shutil.which("brew"):
            mgrs.append("brew")
    elif current_os == "linux":
        for mgr in ["apt", "pacman", "dnf", "yum", "apk"]:
            if shutil.which(mgr):
                mgrs.append(mgr)
    elif current_os == "windows":
        for mgr in ["winget", "choco", "scoop"]:
            if shutil.which(mgr):
                mgrs.append(mgr)

    return mgrs


def generate_remediation_command(binary_dep: BinaryDependency) -> str | None:
    """Generate exact installation command for the current host environment."""
    current_os = get_current_os()
    available_mgrs = detect_available_package_managers()

    # 1. Check custom declared package_names in BinaryDependency
    for mgr in available_mgrs:
        if mgr in binary_dep.package_names:
            pkg = binary_dep.package_names[mgr]
            if mgr == "brew":
                return f"brew install {pkg}"
            if mgr in ("apt", "apt-get"):
                return f"sudo apt-get install -y {pkg}"
            if mgr == "winget":
                return f"winget install {pkg}"
            if mgr == "choco":
                return f"choco install {pkg}"
            if mgr == "pacman":
                return f"sudo pacman -S {pkg}"

    # 2. Check built-in common catalog
    name_key = binary_dep.name.lower()
    if name_key in COMMON_BINARY_PACKAGES:
        pkg_map = COMMON_BINARY_PACKAGES[name_key]
        for mgr in available_mgrs:
            if mgr in pkg_map:
                return pkg_map[mgr]

        # Fallback to default manager for OS if none detected in PATH
        if current_os == "macos" and "brew" in pkg_map:
            return pkg_map["brew"]
        if current_os == "linux" and "apt" in pkg_map:
            return pkg_map["apt"]
        if current_os == "windows" and "winget" in pkg_map:
            return pkg_map["winget"]

    # 3. Generic fallback
    if current_os == "macos":
        return f"brew install {binary_dep.name}"
    if current_os == "linux":
        return f"sudo apt-get install -y {binary_dep.name}"
    if current_os == "windows":
        return f"winget install {binary_dep.name}"

    return None


class AutoRemedyGenerator:
    """Generates copyable shell commands to install missing binaries and Python libraries."""

    def generate_remedies(
        self,
        missing_binaries: list[str],
        missing_packages: list[str],
        target_os: str = "macos",
    ) -> dict[str, str]:
        """Generate platform specific remediation commands."""
        remedies: dict[str, str] = {}
        target_os = target_os.lower()

        # 1. Binary Remedies
        bin_cmds: list[str] = []
        for b in missing_binaries:
            mapping = COMMON_BINARY_PACKAGES.get(b.lower(), {})
            cmd = mapping.get(target_os)
            if not cmd and target_os == "macos":
                cmd = mapping.get("brew")
            elif not cmd and target_os == "linux":
                cmd = mapping.get("apt")
            elif not cmd and target_os == "windows":
                cmd = mapping.get("winget")

            if cmd:
                bin_cmds.append(cmd)
            else:
                if target_os == "macos":
                    bin_cmds.append(f"brew install {b}")
                elif target_os == "windows":
                    bin_cmds.append(f"winget install {b}")
                else:
                    bin_cmds.append(f"sudo apt-get install -y {b}")

        if bin_cmds:
            remedies["system_install"] = " && ".join(bin_cmds)

        # 2. Python Package Remedies (prefer uv pip install)
        if missing_packages:
            pkgs_str = " ".join(missing_packages)
            remedies["python_install"] = f"uv pip install {pkgs_str}"

        return remedies



class AutoRemedyGenerator:
    """Generates copyable shell commands to install missing binaries and Python libraries."""

    BINARY_PACKAGE_MAP: dict[str, dict[str, str]] = {
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
            "windows": "winget install Graphviz.Graphviz",
        },
        "typst": {
            "macos": "brew install typst",
            "linux": "cargo install --locked typst-cli",
            "windows": "winget install --id Typst.Typst",
        },
        "adb": {
            "macos": "brew install android-platform-tools",
            "linux": "sudo apt-get update && sudo apt-get install -y adb",
            "windows": "winget install Google.PlatformTools",
        },
        "tesseract": {
            "macos": "brew install tesseract",
            "linux": "sudo apt-get update && sudo apt-get install -y tesseract-ocr",
            "windows": "winget install UB-Mannheim.TesseractOCR",
        },
    }

    def generate_remedies(
        self,
        missing_binaries: list[str],
        missing_packages: list[str],
        target_os: str = "macos",
    ) -> dict[str, str]:
        """Generate platform specific remediation commands."""
        remedies: dict[str, str] = {}
        target_os = target_os.lower()

        # 1. Binary Remedies
        bin_cmds: list[str] = []
        for b in missing_binaries:
            mapping = self.BINARY_PACKAGE_MAP.get(b.lower(), {})
            cmd = mapping.get(target_os)
            if cmd:
                bin_cmds.append(cmd)
            else:
                # Generic fallback
                if target_os == "macos":
                    bin_cmds.append(f"brew install {b}")
                elif target_os == "windows":
                    bin_cmds.append(f"winget install {b}")
                else:
                    bin_cmds.append(f"sudo apt-get install -y {b}")

        if bin_cmds:
            remedies["system_install"] = " && ".join(bin_cmds)

        # 2. Python Package Remedies (prefer uv pip install)
        if missing_packages:
            pkgs_str = " ".join(missing_packages)
            remedies["python_install"] = f"uv pip install {pkgs_str}"

        return remedies

