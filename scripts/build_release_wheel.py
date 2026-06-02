#!/usr/bin/env python3
"""Build release wheel for myrm-agent-harness with core IP sources stripped.

[INPUT]
- harness_packaging.release::strip_manifest_sources_from_wheel (POS: Release wheel IP source stripping)
- harness_packaging.compiled_core_extra::inject_compiled_core_extra (POS: compiled-core metadata injection)
- harness_packaging.version::read_harness_version (POS: harness version reader)

[OUTPUT]
- main(): Build wheel via ``uv build``, strip manifest ``.py`` in-place (PEP 427)

[POS]
Release-only wheel builder. Pair with ``build_core.py --wheel`` or use ``assemble_production.py``.

Usage::

    uv sync --group build
    .venv/bin/python scripts/build_release_wheel.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from harness_packaging.compiled_core_extra import inject_compiled_core_extra  # noqa: E402
from harness_packaging.release import strip_manifest_sources_from_wheel  # noqa: E402
from harness_packaging.version import read_harness_version  # noqa: E402

_BUILD_SYMLINKS: tuple[str, ...] = ("src", "harness_packaging", "packages", "README.md")


def _build_release_wheel_in_temp(injected_pyproject: str, dist_dir: Path) -> None:
    """Build release wheel from an injected pyproject without mutating the repo tree."""
    with tempfile.TemporaryDirectory(prefix="myrm-release-build-") as tmp:
        tmp_path = Path(tmp)
        for name in _BUILD_SYMLINKS:
            source = _REPO_ROOT / name
            if source.exists():
                os.symlink(source, tmp_path / name, target_is_directory=source.is_dir())
        (tmp_path / "pyproject.toml").write_text(injected_pyproject, encoding="utf-8")
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(dist_dir)],
            check=True,
            cwd=tmp_path,
        )


def main() -> None:
    dist_dir = _REPO_ROOT / "dist"
    dist_dir.mkdir(exist_ok=True)

    pyproject = _REPO_ROOT / "pyproject.toml"
    original_text = pyproject.read_text(encoding="utf-8")
    version = read_harness_version(_REPO_ROOT)
    injected_text = inject_compiled_core_extra(original_text, version)
    _build_release_wheel_in_temp(injected_text, dist_dir)

    wheels = sorted(dist_dir.glob("myrm_agent_harness-*.whl"))
    if not wheels:
        msg = "No harness wheel found in dist/"
        raise SystemExit(msg)

    source_wheel = wheels[-1]
    release_wheel = strip_manifest_sources_from_wheel(source_wheel, in_place=True)
    print(f"Release wheel: {release_wheel}")
    print(f"Stripped core IP .py sources from {source_wheel.name}")


if __name__ == "__main__":
    main()
