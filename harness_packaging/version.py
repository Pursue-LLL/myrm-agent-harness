"""Read harness release version from pyproject.toml."""

from __future__ import annotations

import tomllib
from pathlib import Path

from harness_packaging.manifest import repo_root


def read_harness_version(root: Path | None = None) -> str:
    """Return the ``myrm-agent-harness`` project version string."""
    project_root = root or repo_root()
    pyproject = project_root / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project")
    if not isinstance(project, dict):
        msg = f"Missing [project] table in {pyproject}"
        raise ValueError(msg)
    version = project.get("version")
    if not isinstance(version, str) or not version:
        msg = f"Missing project.version in {pyproject}"
        raise ValueError(msg)
    return version
