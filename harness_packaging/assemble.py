"""Assemble production harness wheels (core .so + release main wheel).

[INPUT]
- harness_packaging.manifest::repo_root (POS: Harness repo path resolver)
- harness_packaging.platforms::{PlatformSpec, get_current_platform} (POS: Eight-platform key detection)
- harness_packaging.release::strip_manifest_sources_from_wheel (POS: Release wheel IP source stripping)

[OUTPUT]
- assemble_production_wheels(): Build platform core wheel and stripped release wheel
- install_production_wheels(): Install dual wheels into a consumer project venv
- run_post_install_verify(): Run verify-harness-distribution after install

[POS]
Production wheel assembly pipeline. Single entry for Docker, Tauri sidecar, and CI builds.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from harness_packaging.manifest import repo_root
from harness_packaging.platforms import PlatformSpec, get_current_platform
from harness_packaging.release import strip_manifest_sources_from_wheel


@dataclass(frozen=True, slots=True)
class ProductionWheels:
    """Paths to platform core and stripped release wheels."""

    core_wheel: Path
    release_wheel: Path
    platform: PlatformSpec


def _build_platform_core_wheel(plat: PlatformSpec) -> Path:
    """Invoke Nuitka compile + platform wheel build."""
    script = repo_root() / "scripts" / "build_core.py"
    subprocess.run(
        [sys.executable, str(script), "--platform", plat.key, "--wheel"],
        check=True,
        cwd=repo_root(),
    )
    wheel_dir = repo_root() / "build" / "core" / "wheels" / plat.key
    wheels = sorted(wheel_dir.glob("*.whl"))
    if not wheels:
        msg = f"No core wheel produced in {wheel_dir}"
        raise RuntimeError(msg)
    return wheels[-1]


def _build_source_wheel(dist_dir: Path) -> Path:
    dist_dir.mkdir(parents=True, exist_ok=True)
    root = repo_root()
    # uv build avoids repo-root build/core/ shadowing PyPA's ``python -m build`` module.
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist_dir)],
        check=True,
        cwd=root,
    )
    wheels = sorted(dist_dir.glob("myrm_agent_harness-*.whl"))
    if not wheels:
        msg = f"No harness wheel produced in {dist_dir}"
        raise RuntimeError(msg)
    return wheels[-1]


def assemble_production_wheels(
    platform: PlatformSpec | None = None,
) -> ProductionWheels:
    """Build platform core wheel and stripped release wheel."""
    plat = platform or get_current_platform()
    dist_dir = repo_root() / "dist"

    core_wheel = _build_platform_core_wheel(plat)
    source_wheel = _build_source_wheel(dist_dir)
    release_wheel = strip_manifest_sources_from_wheel(source_wheel, in_place=True)

    return ProductionWheels(core_wheel=core_wheel, release_wheel=release_wheel, platform=plat)


def _resolve_venv_python(project_dir: Path) -> Path:
    """Return the virtualenv Python interpreter for a consumer project directory."""
    for rel in (".venv/bin/python", ".venv/Scripts/python.exe"):
        candidate = project_dir / rel
        if candidate.is_file():
            return candidate
    msg = f"Virtualenv python not found under {project_dir / '.venv'}"
    raise FileNotFoundError(msg)


def install_production_wheels(
    core_wheel: Path,
    release_wheel: Path,
    *,
    install_dir: Path,
) -> Path:
    """Install core + release wheels into ``install_dir``'s ``.venv`` via uv pip."""
    if not core_wheel.is_file():
        msg = f"Core wheel not found: {core_wheel}"
        raise FileNotFoundError(msg)
    if not release_wheel.is_file():
        msg = f"Release wheel not found: {release_wheel}"
        raise FileNotFoundError(msg)

    venv_python = _resolve_venv_python(install_dir)
    cmd = [
        "uv",
        "pip",
        "install",
        "--python",
        str(venv_python),
        "--reinstall",
        str(core_wheel),
        str(release_wheel),
    ]
    subprocess.run(cmd, check=True, cwd=install_dir)
    return venv_python


def _resolve_verify_command(venv_python: Path) -> Path:
    """Return the ``verify-harness-distribution`` console script beside ``venv_python``."""
    for name in ("verify-harness-distribution", "verify-harness-distribution.exe"):
        candidate = venv_python.parent / name
        if candidate.is_file():
            return candidate
    msg = f"verify-harness-distribution not found next to {venv_python}"
    raise FileNotFoundError(msg)


def run_post_install_verify(venv_python: Path) -> None:
    """Run ``verify-harness-distribution`` after production wheel install."""
    verify_cmd = _resolve_verify_command(venv_python)
    subprocess.run([str(verify_cmd)], check=True)
