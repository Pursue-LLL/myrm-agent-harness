#!/usr/bin/env python3
"""Build release wheel for myrm-agent-harness with core IP sources stripped.

[INPUT]
- harness_packaging.release::{build_harness_source_wheel, finalize_stripped_release_wheel} (POS: Release wheel build + strip + verify)

[OUTPUT]
- main(): Build wheel via ``uv build``, strip manifest ``.py`` in-place (PEP 427), verify artifact

[POS]
Release-only wheel builder. Pair with ``build_core.py --wheel`` or use ``assemble_production.py``.

Usage::

    uv sync --group build
    .venv/bin/python scripts/build_release_wheel.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from harness_packaging.integrity import DistributionWheelArtifactError  # noqa: E402
from harness_packaging.release import (  # noqa: E402
    build_harness_source_wheel,
    finalize_stripped_release_wheel,
)


def main() -> None:
    dist_dir = _REPO_ROOT / "dist"
    source_wheel = build_harness_source_wheel(dist_dir)
    try:
        release_wheel = finalize_stripped_release_wheel(source_wheel, in_place=True)
    except DistributionWheelArtifactError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Release wheel: {release_wheel}")
    print(f"Stripped core IP .py sources from {source_wheel.name}")
    print("Release wheel artifact verification passed")


if __name__ == "__main__":
    main()
