#!/usr/bin/env python3
"""Update component snapshots baseline for Myrm Agent Harness."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from harness_packaging.component_snapshots import get_snapshots_dir, save_snapshots_to_disk


def main() -> int:
    snapshots_dir = get_snapshots_dir()
    print(f"Exporting canonical component snapshots to {snapshots_dir} ...")
    save_snapshots_to_disk(snapshots_dir)
    print("✅ Component snapshots baseline successfully updated!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
