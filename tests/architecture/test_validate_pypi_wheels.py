"""Architecture tests for PyPI upload wheel validation."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ARCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_ARCH_DIR))

from harness_packaging.platforms import PUBLISH_PLATFORMS  # noqa: E402
from harness_packaging.release import manifest_source_paths  # noqa: E402
from scripts.validate_pypi_wheels import expected_wheel_count, validate_upload_dir  # noqa: E402
from distribution_wheel_helpers import (  # noqa: E402
    write_minimal_core_wheel,
    write_minimal_release_wheel,
)


def _touch_valid_wheel(dir_path: Path, name: str) -> Path:
    path = dir_path / name
    if "myrm_agent_harness_core_" in name:
        write_minimal_core_wheel(path)
    else:
        write_minimal_release_wheel(path)
    return path


@pytest.mark.architecture
def test_validate_upload_dir_accepts_full_wheel_set(tmp_path: Path) -> None:
    version = "0.1.0rc2"
    _touch_valid_wheel(tmp_path, f"myrm_agent_harness-{version}-py3-none-any.whl")
    for platform_key in PUBLISH_PLATFORMS:
        token = platform_key.replace("-", "_")
        _touch_valid_wheel(
            tmp_path,
            f"myrm_agent_harness_core_{token}-{version}-cp313-cp313-{platform_key}.whl",
        )
    validate_upload_dir(tmp_path, version)


@pytest.mark.architecture
def test_validate_upload_dir_rejects_missing_core(tmp_path: Path) -> None:
    version = "0.1.0rc2"
    _touch_valid_wheel(tmp_path, f"myrm_agent_harness-{version}-py3-none-any.whl")
    _touch_valid_wheel(
        tmp_path,
        f"myrm_agent_harness_core_linux_x64-{version}-cp313-cp313-linux_x86_64.whl",
    )
    with pytest.raises(SystemExit, match=f"Expected {expected_wheel_count()} wheels"):
        validate_upload_dir(tmp_path, version)


@pytest.mark.architecture
def test_validate_upload_dir_rejects_release_wheel_with_manifest_py(tmp_path: Path) -> None:
    version = "0.1.0rc2"
    manifest_paths = manifest_source_paths()
    release_path = tmp_path / f"myrm_agent_harness-{version}-py3-none-any.whl"
    with zipfile.ZipFile(release_path, "w") as zf:
        zf.writestr("myrm_agent_harness/api/__init__.py", "# public")
        zf.writestr(manifest_paths[0], "# secret")
    for platform_key in PUBLISH_PLATFORMS:
        token = platform_key.replace("-", "_")
        _touch_valid_wheel(
            tmp_path,
            f"myrm_agent_harness_core_{token}-{version}-cp313-cp313-{platform_key}.whl",
        )
    with pytest.raises(SystemExit, match="Manifest .py source must not ship"):
        validate_upload_dir(tmp_path, version)
