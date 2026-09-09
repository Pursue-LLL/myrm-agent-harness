"""Auto remedy command generator for missing binaries and Python packages (Facade over remediation).

[INPUT]
- missing binaries, missing packages, target OS

[OUTPUT]
- AutoRemedyGenerator: maps missing dependencies to platform package manager commands

[POS]
myrm_agent_harness.backends.skills.prerequisites.remedy
"""

from __future__ import annotations

import logging
from typing import Final

logger = logging.getLogger(__name__)

# Common CLI binary to package mappings across package managers
BINARY_PACKAGE_MAP: Final[dict[str, dict[str, str]]] = {
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
            mapping = BINARY_PACKAGE_MAP.get(b.lower(), {})
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
