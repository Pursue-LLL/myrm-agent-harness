"""Tests for the vortexai maintainer run_pytest_safe wrapper script."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "dev" / "run_pytest_safe.py"


def test_run_pytest_safe_true_exits_zero() -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "true"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0


def test_run_pytest_safe_python_timeout_returns_124() -> None:
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--timeout-seconds", "1", "sleep", "5"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 124
