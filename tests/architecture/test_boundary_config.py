"""Test boundary configuration integrity.

Validates that boundary detection configuration is well-formed and correct.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_repo_root))

from scripts.boundary_config import (
    ALLOWED_FRAMEWORK_PREFIXES,
    ALLOWED_PATHS,
    BANNED_PREFIXES,
)


@pytest.mark.architecture
def test_boundary_config_integrity() -> None:
    """Validate that boundary configuration is well-formed and non-empty."""
    # 1. ALLOWED_FRAMEWORK_PREFIXES must not be empty (whitelist mode)
    assert ALLOWED_FRAMEWORK_PREFIXES, "ALLOWED_FRAMEWORK_PREFIXES cannot be empty"

    # 2. Each allowed framework prefix must be a valid Python module name
    for prefix in ALLOWED_FRAMEWORK_PREFIXES:
        assert prefix, "Framework prefix cannot be empty string"
        assert not prefix.startswith("/"), f"Module name should not start with /: {prefix}"
        assert not prefix.endswith("."), f"Module name should not end with dot: {prefix}"
        cleaned = prefix.replace("_", "").replace(".", "")
        assert cleaned.isalnum(), f"Invalid Python module name: {prefix}"

    # 3. BANNED_PREFIXES must not be empty (documentation + clarity)
    assert BANNED_PREFIXES, "BANNED_PREFIXES cannot be empty"

    # 4. Each banned prefix must be a valid Python module name
    for prefix in BANNED_PREFIXES:
        assert prefix, "Banned prefix cannot be empty string"
        assert not prefix.startswith("/"), f"Module name should not start with /: {prefix}"
        assert not prefix.endswith("."), f"Module name should not end with dot: {prefix}"
        cleaned = prefix.replace("_", "").replace(".", "")
        assert cleaned.isalnum(), f"Invalid Python module name: {prefix}"

    # 5. ALLOWED_PATHS must not be empty
    assert ALLOWED_PATHS, "ALLOWED_PATHS cannot be empty"

    # 6. Each allowed path must be a relative path (not absolute)
    for path in ALLOWED_PATHS:
        assert path, "Allowed path cannot be empty string"
        assert not path.startswith("/"), f"Allowed path must be relative: {path}"
        assert not path.endswith("/"), f"Path should not end with /: {path}"

    # 7. No duplicates
    assert len(ALLOWED_FRAMEWORK_PREFIXES) == len(set(ALLOWED_FRAMEWORK_PREFIXES)), (
        "ALLOWED_FRAMEWORK_PREFIXES contains duplicates"
    )
    assert len(BANNED_PREFIXES) == len(set(BANNED_PREFIXES)), "BANNED_PREFIXES contains duplicates"
    assert len(ALLOWED_PATHS) == len(set(ALLOWED_PATHS)), "ALLOWED_PATHS contains duplicates"


def test_framework_prefixes_coverage() -> None:
    """Verify framework prefixes include the harness package."""
    # The framework itself must be in the whitelist
    assert "myrm_agent_harness" in ALLOWED_FRAMEWORK_PREFIXES, "Framework package must be whitelisted"


def test_banned_prefixes_coverage() -> None:
    """Verify banned prefixes cover all expected business layer packages."""
    # Expected business layer packages
    expected_packages = {
        "myrm_agent_server",
        "myrm_control_plane",
        "app",
    }

    actual_packages = set(BANNED_PREFIXES)

    # Check all expected packages are banned
    missing = expected_packages - actual_packages
    assert not missing, f"Missing expected business layer packages: {missing}"


def test_allowed_paths_coverage() -> None:
    """Verify allowed paths cover all expected cross-layer locations."""
    # Expected cross-layer locations
    expected_locations = {
        "tests/integration",
        "benchmarks",
        "scripts",
    }

    actual_locations = set(ALLOWED_PATHS)

    # Check all expected locations are allowed
    missing = expected_locations - actual_locations
    assert not missing, f"Missing expected allowed paths: {missing}"
