#!/usr/bin/env python3
"""Sync generated distribution metadata from harness_packaging/core_manifest.yaml.

[INPUT]
- harness_packaging.codegen::sync_distribution_metadata (POS: Distribution metadata codegen)

[OUTPUT]
- main(): Regenerate _core_ip_manifest.py and compiled-core pins in pyproject.toml

[POS]
Keeps runtime manifest and pyproject optional-deps aligned with core_manifest.yaml SSOT.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from harness_packaging.codegen import sync_distribution_metadata  # noqa: E402
from harness_packaging.integrity import manifest_import_names  # noqa: E402


def main() -> None:
    manifest_path, pyproject_path = sync_distribution_metadata(_REPO_ROOT)
    count = len(manifest_import_names())
    print(f"Generated {manifest_path.relative_to(_REPO_ROOT)} ({count} core IP modules)")
    print(f"Updated {pyproject_path.relative_to(_REPO_ROOT)} compiled-core version pins")


if __name__ == "__main__":
    main()
