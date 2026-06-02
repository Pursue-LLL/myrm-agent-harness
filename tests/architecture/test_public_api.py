"""Architecture tests for the public API boundary."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from harness_packaging.manifest import load_core_manifest

_MANIFEST_PATH = _REPO_ROOT / "harness_packaging" / "core_manifest.yaml"


@pytest.mark.architecture
def test_public_api_exports_are_importable() -> None:
    """All symbols in api.__all__ must resolve without error."""
    api = importlib.import_module("myrm_agent_harness.api")
    for name in api.__all__:
        assert hasattr(api, name), f"Missing public API export: {name}"


@pytest.mark.architecture
def test_public_api_factory_reexport() -> None:
    """create_skill_agent must be callable via the public API."""
    from myrm_agent_harness.api import create_skill_agent

    assert callable(create_skill_agent)


@pytest.mark.architecture
def test_distribution_mode_defaults_to_source() -> None:
    """Editable dev installs should report source distribution."""
    from myrm_agent_harness._distribution import DistributionMode, get_distribution_mode

    assert get_distribution_mode() is DistributionMode.SOURCE


@pytest.mark.architecture
def test_core_manifest_modules_exist() -> None:
    """Every module listed in core_manifest.yaml must exist on disk."""
    manifest = load_core_manifest(_MANIFEST_PATH)
    assert len(manifest.module_paths) >= 1
    for path in manifest.module_paths:
        assert path.is_file(), f"Manifest module missing: {path}"


@pytest.mark.architecture
def test_api_package_has_no_heavy_side_effects_on_import() -> None:
    """Importing api.types must not pull in the agent factory."""
    import sys

    before = set(sys.modules)
    importlib.import_module("myrm_agent_harness.api.types")
    after = set(sys.modules)
    loaded = after - before
    assert "myrm_agent_harness.agent.skill_agent_factory" not in loaded
