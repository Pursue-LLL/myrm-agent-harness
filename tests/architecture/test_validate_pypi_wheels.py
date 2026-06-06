"""Architecture tests for PyPI upload wheel validation."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from scripts.validate_pypi_wheels import validate_upload_dir


def _touch(dir_path: Path, name: str) -> Path:
    path = dir_path / name
    path.write_bytes(b"")
    return path


def test_validate_upload_dir_accepts_seven_wheels(tmp_path: Path) -> None:
    version = "0.1.0rc2"
    _touch(tmp_path, f"myrm_agent_harness-{version}-py3-none-any.whl")
    for platform_key in (
        "darwin-arm64",
        "darwin-x64",
        "linux-x64",
        "linux-arm64",
        "win32-x64",
        "win32-arm64",
    ):
        token = platform_key.replace("-", "_")
        _touch(tmp_path, f"myrm_agent_harness_core_{token}-{version}-cp313-cp313-{platform_key}.whl")
    validate_upload_dir(tmp_path, version)


def test_validate_upload_dir_rejects_missing_core(tmp_path: Path) -> None:
    version = "0.1.0rc2"
    _touch(tmp_path, f"myrm_agent_harness-{version}-py3-none-any.whl")
    _touch(tmp_path, f"myrm_agent_harness_core_linux_x64-{version}-cp313-cp313-linux_x86_64.whl")
    try:
        validate_upload_dir(tmp_path, version)
    except SystemExit as exc:
        assert "Expected 7 wheels" in str(exc)
    else:
        raise AssertionError("expected SystemExit for incomplete wheel set")
