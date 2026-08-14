"""Architecture test: Python package roots must not flat-spread implementation modules."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_PACKAGE_ROOT = _REPO_ROOT / "src" / "myrm_agent_harness"
_CHECK_SCRIPT = _REPO_ROOT / "scripts" / "check_package_root_layout.py"

_DISTRIBUTION_SUBPACKAGE = _PACKAGE_ROOT / "distribution"

_REQUIRED_SUBPACKAGE_FILES = (
    "__init__.py",
    "_ARCH.md",
    "core_ip_manifest.py",
    "probe.py",
    "runtime_platform.py",
    "verify.py",
)

_FORBIDDEN_LEGACY_FLAT_FILES = (
    "_distribution.py",
    "_runtime_platform.py",
    "_core_ip_manifest.py",
    "_verify_distribution.py",
)


@pytest.mark.architecture
def test_package_root_layout_gate() -> None:
    result = subprocess.run(
        [sys.executable, str(_CHECK_SCRIPT), "--root", str(_PACKAGE_ROOT)],
        cwd=_REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.architecture
def test_distribution_subpackage_layout() -> None:
    assert _DISTRIBUTION_SUBPACKAGE.is_dir(), f"Missing {_DISTRIBUTION_SUBPACKAGE}. See distribution/_ARCH.md."
    for filename in _REQUIRED_SUBPACKAGE_FILES:
        path = _DISTRIBUTION_SUBPACKAGE / filename
        assert path.is_file(), f"Missing required distribution module file: {path}"


@pytest.mark.architecture
@pytest.mark.parametrize("legacy_filename", _FORBIDDEN_LEGACY_FLAT_FILES)
def test_distribution_legacy_flat_files_removed(legacy_filename: str) -> None:
    legacy_path = _PACKAGE_ROOT / legacy_filename
    assert not legacy_path.exists(), (
        f"Legacy flat distribution file must not reappear: {legacy_path}. Use distribution/ subpackage instead."
    )


@pytest.mark.architecture
def test_distribution_public_export() -> None:
    from myrm_agent_harness.distribution import (
        DistributionMode,
        assert_distribution_ready,
        get_distribution_mode,
    )
    from myrm_agent_harness.distribution.probe import (
        DistributionMode as ModeFromProbe,
    )
    from myrm_agent_harness.distribution.probe import (
        assert_distribution_ready as ready_from_probe,
    )

    assert DistributionMode is ModeFromProbe
    assert assert_distribution_ready is ready_from_probe
    assert get_distribution_mode() is not None


@pytest.mark.architecture
def test_client_facade_still_at_package_root() -> None:
    client_path = _PACKAGE_ROOT / "client.py"
    assert client_path.is_file(), "SDK facade client.py must remain at package root."


@pytest.mark.architecture
def test_api_distribution_lazy_export() -> None:
    from myrm_agent_harness.api import get_distribution_mode, is_compiled_distribution

    assert get_distribution_mode is not None
    assert is_compiled_distribution is not None
