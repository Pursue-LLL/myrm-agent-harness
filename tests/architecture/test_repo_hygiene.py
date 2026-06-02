"""Architecture tests for repository hygiene after monorepo export."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_FORBIDDEN_PREFIXES = (
    "myrm-agent-harness/",
    "myrm-agent-server/",
)

_FORBIDDEN_SUFFIXES = (
    ".db",
)


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=_REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


@pytest.mark.architecture
def test_no_forbidden_tracked_paths() -> None:
    violations: list[str] = []
    for path in _tracked_files():
        if any(path.endswith(suffix) for suffix in _FORBIDDEN_SUFFIXES):
            violations.append(path)
        if any(path.startswith(prefix) for prefix in _FORBIDDEN_PREFIXES):
            violations.append(path)
    assert not violations, (
        "Forbidden paths tracked in git (remove and add to .gitignore): "
        + ", ".join(sorted(violations))
    )
