"""Architecture gate: algorithm-zone modules must be manifest-covered or explicitly public."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from harness_packaging.integrity import DISTRIBUTION_PUBLIC_MARKER, manifest_watch_violations

_GATE_HINT = (
    f"Add the directory to harness_packaging/core_manifest.yaml or mark the module with "
    f"{DISTRIBUTION_PUBLIC_MARKER} in its docstring/header."
)


@pytest.mark.architecture
def test_manifest_watch_violations_empty_on_current_tree() -> None:
    assert manifest_watch_violations() == ()


@pytest.mark.architecture
def test_algorithm_zone_modules_are_manifest_covered_or_public() -> None:
    """Prevent accidental plaintext IP in release wheels under algorithm watch zones."""
    violations = manifest_watch_violations()
    if violations:
        joined = "\n  - ".join(violations)
        pytest.fail(
            "Algorithm-zone modules missing manifest coverage or public marker:\n"
            f"  - {joined}\n"
            f"{_GATE_HINT}"
        )
