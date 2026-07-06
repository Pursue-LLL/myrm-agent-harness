"""Architecture gate: tests/toolkits/ must mirror shipped toolkits with real tests.

Prevents dead empty directories (e.g. removed toolkit left orphan test folder).
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOLKITS_SRC = _REPO_ROOT / "src" / "myrm_agent_harness" / "toolkits"
_TOOLKITS_TESTS = _REPO_ROOT / "tests" / "toolkits"


@pytest.mark.architecture
def test_toolkits_test_dirs_mirror_src_packages() -> None:
    violations: list[str] = []

    for test_dir in sorted(_TOOLKITS_TESTS.iterdir()):
        if not test_dir.is_dir():
            continue
        if test_dir.name.startswith(".") or test_dir.name == "__pycache__":
            continue

        src_pkg = _TOOLKITS_SRC / test_dir.name
        if not src_pkg.is_dir():
            violations.append(
                f"{test_dir.relative_to(_REPO_ROOT)} has no matching "
                f"src/myrm_agent_harness/toolkits/{test_dir.name}/ — delete or restore toolkit"
            )
            continue

        has_tests = any(test_dir.rglob("test_*.py"))
        if not has_tests:
            violations.append(
                f"{test_dir.relative_to(_REPO_ROOT)} is empty (no test_*.py) — delete or add tests"
            )

    assert not violations, "tests/toolkits mirror violations:\n" + "\n".join(violations)
