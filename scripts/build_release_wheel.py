#!/usr/bin/env python3
"""Build release wheel for myrm-agent-harness with core IP sources stripped.

[INPUT]
- harness_packaging.release::strip_manifest_sources_from_wheel (POS: Release wheel IP source stripping)

[OUTPUT]
- main(): Build wheel via ``uv build``, strip manifest ``.py`` in-place (PEP 427)

[POS]
Release-only wheel builder. Pair with ``build_core.py --wheel`` or use ``assemble_production.py``.

Usage::

    uv sync --group build
    .venv/bin/python scripts/build_release_wheel.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from harness_packaging.release import strip_manifest_sources_from_wheel  # noqa: E402


def main() -> None:
    dist_dir = _REPO_ROOT / "dist"
    dist_dir.mkdir(exist_ok=True)

    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist_dir)],
        check=True,
        cwd=_REPO_ROOT,
    )

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
