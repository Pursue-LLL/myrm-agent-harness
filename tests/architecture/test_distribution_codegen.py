"""Architecture tests for distribution metadata codegen."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from harness_packaging.codegen import (  # noqa: E402
    generated_core_ip_manifest_path,
    render_compiled_core_sections,
    render_core_ip_manifest_module,
)
from harness_packaging.integrity import manifest_import_names, manifest_source_relpaths  # noqa: E402
from harness_packaging.manifest import load_core_manifest  # noqa: E402
from harness_packaging.version import read_harness_version  # noqa: E402
from myrm_agent_harness._core_ip_manifest import CORE_IP_IMPORTS  # noqa: E402


@pytest.mark.architecture
def test_core_manifest_directory_expansion_covers_algorithm_subtrees() -> None:
    """Core IP directories must resolve to the expected protected module count."""
    manifest = load_core_manifest()
    assert len(manifest.module_paths) == 81
    assert len(manifest_import_names()) == 81
    assert len(manifest_source_relpaths()) == 81


@pytest.mark.architecture
def test_generated_core_ip_manifest_matches_yaml_ssot() -> None:
    """Generated runtime manifest must match YAML-derived import paths."""
    yaml_names = manifest_import_names()
    assert CORE_IP_IMPORTS == yaml_names


@pytest.mark.architecture
def test_generated_core_ip_manifest_file_is_fresh() -> None:
    """Fail when _core_ip_manifest.py drifts from core_manifest.yaml."""
    from harness_packaging.integrity import manifest_import_names, manifest_source_relpaths

    path = generated_core_ip_manifest_path(_REPO_ROOT)
    on_disk = path.read_text(encoding="utf-8")
    expected = render_core_ip_manifest_module(manifest_import_names(), manifest_source_relpaths())
    assert on_disk == expected


@pytest.mark.architecture
def test_all_core_ip_imports_are_importable() -> None:
    """Every generated import path must resolve in editable source installs."""
    import importlib

    for import_name in CORE_IP_IMPORTS:
        importlib.import_module(import_name)


@pytest.mark.architecture
def test_compiled_core_pins_match_project_version() -> None:
    """compiled-core optional deps must pin the same version as project.version."""
    version = read_harness_version(_REPO_ROOT)
    pyproject = (_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    glibc_section, musl_section = render_compiled_core_sections(version)
    for line in glibc_section.splitlines():
        if "myrm-agent-harness-core-" in line:
            assert f"=={version}" in line
    for line in musl_section.splitlines():
        if "myrm-agent-harness-core-" in line:
            assert f"=={version}" in line
    assert f"myrm-agent-harness-core-darwin-arm64=={version}" in pyproject
    assert f"myrm-agent-harness-core-linux-x64-musl=={version}" in pyproject


@pytest.mark.architecture
def test_core_ip_import_names_never_use_init_suffix() -> None:
    """Package __init__ modules must map to parent import paths, not ``.__init__``."""
    assert all(not name.endswith(".__init__") for name in CORE_IP_IMPORTS)


@pytest.mark.architecture
def test_nuitka_compile_input_uses_package_dir_for_init() -> None:
    """Package __init__.py must compile its directory, not the file path."""
    from harness_packaging.nuitka_compile import nuitka_artifact_stem, nuitka_compile_input

    init_file = (
        _REPO_ROOT
        / "src/myrm_agent_harness/agent/context_management/pipeline/__init__.py"
    )
    assert nuitka_compile_input(init_file) == init_file.parent
    assert nuitka_artifact_stem(init_file) == "pipeline"

    module_file = init_file.parent / "engine.py"
    assert nuitka_compile_input(module_file) == module_file
    assert nuitka_artifact_stem(module_file) == "engine"


@pytest.mark.architecture
def test_runtime_platform_key_is_supported() -> None:
    """Runtime platform detection must resolve to a published core wheel key."""
    from harness_packaging.runtime_platform import get_runtime_platform_key
    from harness_packaging.platforms import SUPPORTED_PLATFORMS
    from myrm_agent_harness._runtime_platform import get_runtime_platform_key as shipped_key

    key = get_runtime_platform_key()
    assert key in SUPPORTED_PLATFORMS
    assert key == shipped_key()


@pytest.mark.architecture
def test_public_api_does_not_export_core_ip_internals() -> None:
    """Third-party consumers must use myrm_agent_harness.api, not core IP modules."""
    api = __import__("myrm_agent_harness.api", fromlist=["__all__"])
    exported = set(api.__all__)
    for import_name in CORE_IP_IMPORTS:
        short_name = import_name.rsplit(".", maxsplit=1)[-1]
        assert short_name not in exported
        assert import_name not in exported
