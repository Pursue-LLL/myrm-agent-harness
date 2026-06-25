#!/usr/bin/env python3
"""Build Nuitka-compiled core modules and platform-specific wheels.

Usage::

    uv sync --group build
    .venv/bin/python scripts/build_core.py                  # compile for current platform
    .venv/bin/python scripts/build_core.py --wheel          # compile + build platform wheel
    .venv/bin/python scripts/build_core.py --list           # show manifest modules

Requires ``nuitka`` in the active environment (``uv sync --group build``).
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from harness_packaging.manifest import load_core_manifest  # noqa: E402
from harness_packaging.platforms import (  # noqa: E402
    PlatformSpec,
    core_package_name,
    get_current_platform,
    platform_spec_for_key,
)
from harness_packaging.version import read_harness_version  # noqa: E402

_BUILD_ROOT = _REPO_ROOT / "build" / "core"
_STAGING_ROOT = _BUILD_ROOT / "staging"
_WHEEL_OUT = _BUILD_ROOT / "wheels"


def _require_nuitka() -> None:
    if importlib.util.find_spec("nuitka") is None:
        msg = (
            "Nuitka is required for core compilation. "
            "Install with: uv sync --group build"
        )
        raise SystemExit(msg)


def _module_import_name(module_file: Path) -> str:
    rel = module_file.relative_to(_REPO_ROOT / "src")
    parts = rel.with_suffix("").parts
    return ".".join(parts)


def _compile_module(
    module_file: Path,
    compile_root: Path,
    platform: PlatformSpec,
    *,
    native: bool,
) -> Path:
    import_name = _module_import_name(module_file)
    rel = module_file.relative_to(_REPO_ROOT / "src" / "myrm_agent_harness")
    # Isolated output dir per module path — avoids stem collisions (e.g. two engine.py).
    output_dir = compile_root / rel.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = [
        sys.executable,
        "-m",
        "nuitka",
        "--module",
        str(module_file),
        f"--output-dir={output_dir}",
        "--assume-yes-for-downloads",
        "--remove-output",
    ]
    # Only pass --target for cross-compilation; native builds break with wrong target.
    if not native and platform.nuitka_target is not None:
        cmd.append(f"--target={platform.nuitka_target}")

    print(f"Compiling {import_name} ...")
    subprocess.run(cmd, check=True, cwd=_REPO_ROOT)

    stem = module_file.stem
    candidates = sorted(output_dir.glob(f"{stem}*.so")) + sorted(output_dir.glob(f"{stem}*.pyd"))
    if not candidates:
        msg = f"No compiled artifact produced for {module_file}"
        raise RuntimeError(msg)
    return candidates[0]


def _stage_artifacts(
    compiled: list[tuple[Path, Path]],
    staging_root: Path,
) -> None:
    """Copy compiled artifacts into myrm_agent_harness package tree under staging/."""
    if staging_root.exists():
        shutil.rmtree(staging_root)
    pkg_root = staging_root / "myrm_agent_harness"
    for module_file, artifact in compiled:
        rel = module_file.relative_to(_REPO_ROOT / "src" / "myrm_agent_harness")
        dest_dir = pkg_root / rel.parent
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(artifact, dest_dir / artifact.name)
        print(f"  staged {rel.parent / artifact.name}")


def compile_core(platform: PlatformSpec | None = None) -> Path:
    """Compile all manifest modules and stage under build/core/staging/."""
    _require_nuitka()
    plat = platform or get_current_platform()
    manifest = load_core_manifest()
    compile_dir = _BUILD_ROOT / "compile" / plat.key
    compile_dir.mkdir(parents=True, exist_ok=True)

    current = get_current_platform()
    native = plat.key == current.key

    compiled: list[tuple[Path, Path]] = []
    for module_file in manifest.module_paths:
        artifact = _compile_module(module_file, compile_dir, plat, native=native)
        compiled.append((module_file, artifact))

    _stage_artifacts(compiled, _STAGING_ROOT)
    print(f"Compiled {len(compiled)} core modules for {plat.key}")
    return _STAGING_ROOT


def _wheel_force_include_toml(artifacts_root: Path, compiled_prefix: str) -> str:
    """Generate hatch ``force-include`` table for compiled artifacts."""
    entries: list[str] = []
    for pattern in ("*.so", "*.pyd"):
        for artifact in sorted(artifacts_root.rglob(pattern)):
            rel = artifact.relative_to(artifacts_root).as_posix()
            source = f"{compiled_prefix}/{rel}"
            dest = f"myrm_agent_harness/{rel}"
            entries.append(f'"{source}" = "{dest}"')
    if not entries:
        msg = f"No compiled artifacts under {artifacts_root}"
        raise FileNotFoundError(msg)
    body = "\n".join(entries)
    return f"\n[tool.hatch.build.targets.wheel.force-include]\n{body}\n"


def _prepare_core_wheel_project(
    tmp_dir: Path,
    *,
    pkg_dir: Path,
    plat: PlatformSpec,
    artifacts_root: Path,
    harness_version: str,
) -> None:
    shutil.copytree(pkg_dir / "src", tmp_dir / "src")
    compiled_dest = tmp_dir / "compiled" / "myrm_agent_harness"
    shutil.copytree(artifacts_root, compiled_dest)

    init_path = tmp_dir / "src" / "myrm_agent_harness_core" / "__init__.py"
    init_text = init_path.read_text(encoding="utf-8")
    init_text = init_text.replace(
        '__platform_key__: str = "unknown"',
        f'__platform_key__: str = "{plat.key}"',
        1,
    )
    init_text = re.sub(
        r'^__version__ = "[^"]+"',
        f'__version__ = "{harness_version}"',
        init_text,
        count=1,
        flags=re.MULTILINE,
    )
    init_path.write_text(init_text, encoding="utf-8")

    base_toml = (pkg_dir / "pyproject.toml").read_text(encoding="utf-8")
    dynamic_toml = base_toml.replace(
        'name = "myrm-agent-harness-core"',
        f'name = "{core_package_name(plat.key)}"',
        1,
    )
    dynamic_toml = re.sub(
        r'^version = "[^"]+"',
        f'version = "{harness_version}"',
        dynamic_toml,
        count=1,
        flags=re.MULTILINE,
    )
    dynamic_toml = dynamic_toml.replace(
        "dependencies = []",
        f'dependencies = [\n  "myrm-agent-harness=={harness_version}",\n]',
        1,
    )
    dynamic_toml = re.sub(
        r"\n\[tool\.hatch\.build\.hooks\.custom\][^\[]*",
        "\n",
        dynamic_toml,
        count=1,
    )
    dynamic_toml += _wheel_force_include_toml(
        artifacts_root,
        compiled_prefix="compiled/myrm_agent_harness",
    )
    (tmp_dir / "pyproject.toml").write_text(dynamic_toml, encoding="utf-8")


def build_platform_wheel(platform: PlatformSpec | None = None) -> Path:
    """Compile core modules and build a platform-specific wheel."""
    plat = platform or get_current_platform()
    compile_core(plat)

    pkg_dir = _REPO_ROOT / "packages" / "myrm-agent-harness-core"
    wheel_out = _WHEEL_OUT / plat.key
    wheel_out.mkdir(parents=True, exist_ok=True)

    artifacts_root = _STAGING_ROOT / "myrm_agent_harness"
    dist_name = core_package_name(plat.key)
    harness_version = read_harness_version(_REPO_ROOT)

    with tempfile.TemporaryDirectory(prefix="myrm-core-wheel-") as tmp:
        tmp_dir = Path(tmp)
        _prepare_core_wheel_project(
            tmp_dir,
            pkg_dir=pkg_dir,
            plat=plat,
            artifacts_root=artifacts_root,
            harness_version=harness_version,
        )

        cmd = [sys.executable, "-m", "build", str(tmp_dir), "--outdir", str(wheel_out), "--wheel"]
        print(f"Building wheel {dist_name} ...")
        subprocess.run(cmd, check=True, cwd=_REPO_ROOT)

    wheels = sorted(wheel_out.glob("*.whl"))
    if not wheels:
        msg = "Wheel build produced no artifacts"
        raise RuntimeError(msg)
    print(f"Wheel ready: {wheels[-1]}")
    return wheels[-1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build compiled core modules for myrm-agent-harness")
    parser.add_argument("--wheel", action="store_true", help="Also build platform-specific wheel")
    parser.add_argument("--list", action="store_true", help="List manifest modules and exit")
    parser.add_argument(
        "--platform",
        default=None,
        help="Override platform key (e.g. darwin-arm64). Defaults to auto-detect.",
    )
    args = parser.parse_args()

    if args.list:
        manifest = load_core_manifest()
        for path in manifest.module_paths:
            print(path.relative_to(_REPO_ROOT))
        return

    if args.platform is not None:
        platform = platform_spec_for_key(args.platform)
    else:
        platform = get_current_platform()

    if args.wheel:
        build_platform_wheel(platform)
    else:
        compile_core(platform)


if __name__ == "__main__":
    main()
