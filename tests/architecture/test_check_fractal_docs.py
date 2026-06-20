"""Architecture test: harness package directories must have _ARCH.md."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CHECK_SCRIPT = _REPO_ROOT / "scripts" / "check_fractal_docs.py"


@pytest.mark.architecture
def test_harness_fractal_arch_coverage() -> None:
    result = subprocess.run(
        [sys.executable, str(_CHECK_SCRIPT)],
        cwd=_REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
