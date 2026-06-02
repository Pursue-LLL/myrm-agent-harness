"""Architecture tests for distribution packaging."""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from harness_packaging.integrity import manifest_import_names
from harness_packaging.manifest import load_core_manifest
from harness_packaging.platforms import SUPPORTED_PLATFORMS, get_current_platform
from harness_packaging.release import manifest_source_paths, strip_manifest_sources_from_wheel
from harness_packaging.version import read_harness_version
from myrm_agent_harness._core_ip_manifest import CORE_IP_IMPORTS

_MANIFEST_PATH = _REPO_ROOT / "harness_packaging" / "core_manifest.yaml"

_SKIP_UNDER_XDIST = pytest.mark.skipif(
    os.environ.get("PYTEST_XDIST_WORKER") is not None,
    reason="Wheel build tests invoke Nuitka/subprocess and require pytest -n0",
)


@pytest.mark.architecture
def test_platform_detection_returns_known_key() -> None:
    plat = get_current_platform()
    assert plat.key in SUPPORTED_PLATFORMS


@pytest.mark.architecture
def test_manifest_source_paths_match_yaml() -> None:
    manifest = load_core_manifest()
    paths = manifest_source_paths()
    assert len(paths) == len(manifest.module_paths)
    for path in paths:
        assert path.startswith("myrm_agent_harness/")
        assert path.endswith(".py")


@pytest.mark.architecture
def test_read_harness_version_matches_pyproject() -> None:
    version = read_harness_version(_REPO_ROOT)
    assert version == "0.1.0"


@pytest.mark.architecture
def test_core_ip_manifest_matches_yaml() -> None:
    yaml_names = manifest_import_names()
    assert yaml_names == CORE_IP_IMPORTS


@pytest.mark.architecture
def test_strip_manifest_sources_from_wheel(tmp_path: Path) -> None:
    manifest_paths = manifest_source_paths()
    wheel_path = tmp_path / "myrm_agent_harness-0.1.0-py3-none-any.whl"
    release_path = tmp_path / "out.whl"

    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("myrm_agent_harness/api/__init__.py", "# public")
        zf.writestr(manifest_paths[0], "# secret")
        zf.writestr("myrm_agent_harness/agent/other.py", "# ok")

    result = strip_manifest_sources_from_wheel(wheel_path, release_path)
    assert result == release_path

    with zipfile.ZipFile(release_path, "r") as zf:
        names = zf.namelist()
    assert manifest_paths[0] not in names
    assert "myrm_agent_harness/api/__init__.py" in names
    assert "myrm_agent_harness/agent/other.py" in names


@pytest.mark.architecture
def test_strip_manifest_in_place_preserves_pep427_name(tmp_path: Path) -> None:
    manifest_paths = manifest_source_paths()
    wheel_path = tmp_path / "myrm_agent_harness-0.1.0-py3-none-any.whl"

    with zipfile.ZipFile(wheel_path, "w") as zf:
        zf.writestr("myrm_agent_harness/api/__init__.py", "# public")
        zf.writestr(manifest_paths[0], "# secret")

    result = strip_manifest_sources_from_wheel(wheel_path, in_place=True)
    assert result.name == "myrm_agent_harness-0.1.0-py3-none-any.whl"
    assert result.is_file()


@pytest.mark.architecture
@_SKIP_UNDER_XDIST
def test_core_wheel_contains_compiled_artifacts() -> None:
    """Platform core wheel must ship Nuitka .so/.pyd for manifest modules."""
    subprocess.run(
        [sys.executable, str(_REPO_ROOT / "scripts" / "build_core.py"), "--wheel"],
        check=True,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    plat = get_current_platform()
    wheel_dir = _REPO_ROOT / "build" / "core" / "wheels" / plat.key
    wheels = sorted(wheel_dir.glob("*.whl"))
    assert wheels, f"No core wheel in {wheel_dir}"

    with zipfile.ZipFile(wheels[-1], "r") as zf:
        names = zf.namelist()
    compiled = [n for n in names if n.startswith("myrm_agent_harness/") and (n.endswith(".so") or n.endswith(".pyd"))]
    assert len(compiled) == len(manifest_source_paths()), compiled
    assert any("agent/skills/evolution/core/engine" in n for n in compiled)
    assert any("agent/context_management/pipeline/engine" in n for n in compiled)


@pytest.mark.architecture
@_SKIP_UNDER_XDIST
def test_release_wheel_is_uv_installable(tmp_path: Path) -> None:
    """Release wheel filename must be PEP 427 compliant for uv pip install."""
    subprocess.run(
        [sys.executable, str(_REPO_ROOT / "scripts" / "build_release_wheel.py")],
        check=True,
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
    )
    wheels = sorted((_REPO_ROOT / "dist").glob("myrm_agent_harness-*.whl"))
    assert wheels, "build_release_wheel did not produce a wheel"
    wheel_path = wheels[-1]

    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    venv_python = venv / "bin" / "python"
    if not venv_python.exists():
        venv_python = venv / "Scripts" / "python.exe"
    result = subprocess.run(
        ["uv", "pip", "install", "--python", str(venv_python), str(wheel_path)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.architecture
def test_verify_distribution_in_source_mode() -> None:
    """verify-harness-distribution must pass on editable dev installs (all .py source)."""
    from importlib.metadata import entry_points

    script_names = {ep.name for ep in entry_points(group="console_scripts")}
    assert "verify-harness-distribution" in script_names

    verify_cmd = _REPO_ROOT / ".venv" / "bin" / "verify-harness-distribution"
    if not verify_cmd.exists():
        verify_cmd = _REPO_ROOT / ".venv" / "Scripts" / "verify-harness-distribution.exe"
    assert verify_cmd.is_file(), f"Console script missing: {verify_cmd}"

    subprocess.run([str(verify_cmd)], check=True, cwd=_REPO_ROOT)
    subprocess.run(
        [sys.executable, "-m", "myrm_agent_harness._verify_distribution"],
        check=True,
        cwd=_REPO_ROOT,
    )
