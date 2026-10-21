#!/usr/bin/env python3
"""Assert git tag version matches pyproject.toml project.version.

[INPUT]
- GITHUB_REF env (refs/tags/vX.Y.Z on tag push)

[OUTPUT]
- main(): exit 0 when tag matches or push is not a version tag

[POS]
First gate in publish-pypi.yml before expensive core wheel builds.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from harness_packaging.version import read_harness_version  # noqa: E402


def main() -> int:
    ref = os.environ.get("GITHUB_REF", "")
    if not ref.startswith("refs/tags/v"):
        print("Not a version tag push; skipping tag gate")
        return 0

    tag_version = ref.removeprefix("refs/tags/v")
    pyproject_version = read_harness_version(_REPO_ROOT)
    if tag_version != pyproject_version:
        msg = (
            f"Tag v{tag_version} does not match pyproject.toml version {pyproject_version}. "
            "Bump project.version or retag before publishing."
        )
        print(msg, file=sys.stderr)
        return 1

    print(f"Tag matches pyproject version: {pyproject_version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
