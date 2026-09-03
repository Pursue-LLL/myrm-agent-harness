"""Architecture gate: Pytest Warning CI Gate configuration assertion.

Asserts that:
1. pyproject.toml [tool.pytest.ini_options].filterwarnings contains "error" as its default root rule.
2. Any ignored warnings are explicitly qualified (no catch-all "ignore" without qualification).
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))


@pytest.mark.architecture
def test_pytest_warning_gate_configured_as_error() -> None:
    """Verify that filterwarnings is configured with 'error' default fail-closed policy."""
    pyproject_path = _REPO_ROOT / "pyproject.toml"
    assert pyproject_path.is_file(), f"pyproject.toml not found at {pyproject_path}"

    config = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    pytest_opts = config.get("tool", {}).get("pytest", {}).get("ini_options", {})
    filterwarnings = pytest_opts.get("filterwarnings", [])

    assert isinstance(
        filterwarnings, list
    ), "tool.pytest.ini_options.filterwarnings must be a list"
    assert len(filterwarnings) > 0, "filterwarnings must not be empty"

    # Root rule must be "error"
    assert (
        filterwarnings[0] == "error"
    ), f"filterwarnings root rule must be 'error' to enforce zero-warning policy, got {filterwarnings[0]!r}"

    # Ensure no bare catch-all "ignore" rules exist
    for rule in filterwarnings:
        if rule == "error":
            continue
        assert rule.startswith(
            "ignore:"
        ), f"Warning filter rule must start with 'ignore:' or be 'error', got {rule!r}"
        # Disallow bare 'ignore' without reason or module
        assert rule != "ignore", "Bare 'ignore' rule is forbidden in CI warning gate"
