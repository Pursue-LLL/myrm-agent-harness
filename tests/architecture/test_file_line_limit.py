"""Architecture test: Python files must respect line-count gate."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CHECK_SCRIPT = _REPO_ROOT / "scripts" / "check_file_line_limit.py"
_BASELINE = _REPO_ROOT / "scripts" / "file_line_baseline.txt"


@pytest.mark.architecture
def test_harness_file_line_limit_gate() -> None:
    result = subprocess.run(
        [sys.executable, str(_CHECK_SCRIPT), "--baseline", str(_BASELINE)],
        cwd=_REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
