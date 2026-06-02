"""Platform-specific compiled core extensions for myrm-agent-harness.

This package is installed alongside ``myrm-agent-harness`` (mirrors Claude Code's
per-platform native binary packages).  It places Nuitka-compiled ``.so`` artifacts
into the ``myrm_agent_harness`` namespace so imports resolve transparently.
"""

from __future__ import annotations

from pathlib import Path

__version__ = "0.1.0"


def get_platform_key() -> str:
    """Return the platform key this wheel was built for."""
    return __platform_key__


def install_core_artifacts() -> list[Path]:
    """Copy staged compiled artifacts into site-packages (no-op at import time).

    Artifacts are installed directly into ``myrm_agent_harness/`` by the wheel
    layout; this helper exists for diagnostics and future migration hooks.
    """
    installed: list[Path] = []
    root = Path(__file__).resolve().parent / "_artifacts"
    if not root.is_dir():
        return installed
    for artifact in root.rglob("*.so"):
        installed.append(artifact)
    for artifact in root.rglob("*.pyd"):
        installed.append(artifact)
    return installed


# Replaced at wheel build time by hatch hook.
__platform_key__: str = "unknown"
