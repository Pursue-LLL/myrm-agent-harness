#!/usr/bin/env python3
"""Validate wheel artifacts before PyPI upload.

[INPUT]
- harness_packaging.platforms::SUPPORTED_PLATFORMS (POS: platform key registry)
- harness_packaging.version::read_harness_version (POS: harness version reader)

[OUTPUT]
- main(): exit 0 when upload dir has exactly 7 version-matched wheels

[POS]
Release pipeline gate preventing partial PyPI publishes.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from harness_packaging.platforms import SUPPORTED_PLATFORMS  # noqa: E402
from harness_packaging.version import read_harness_version  # noqa: E402

_RELEASE_PREFIX = "myrm_agent_harness-"


def _normalize_version(version: str) -> str:
    return version.replace("-", "").replace(".", "").lower()


def _wheel_version(path: Path) -> str | None:
    match = re.search(r"-([0-9][0-9a-zA-Z.]*)-", path.name)
    if match is None:
        return None
    return match.group(1)


def _is_release_wheel(path: Path) -> bool:
    name = path.name
    return name.startswith(_RELEASE_PREFIX) and "core" not in name


def _platform_from_core_wheel(path: Path) -> str | None:
    for platform_key in SUPPORTED_PLATFORMS:
        token = platform_key.replace("-", "_")
        if f"myrm_agent_harness_core_{token}-" in path.name:
            return platform_key
    return None


def validate_upload_dir(upload_dir: Path, expected_version: str) -> None:
    wheels = sorted(upload_dir.glob("*.whl"))
    if len(wheels) != 7:
        msg = f"Expected 7 wheels (1 release + 6 core), found {len(wheels)} in {upload_dir}"
        raise SystemExit(msg)

    release_wheels = [wheel for wheel in wheels if _is_release_wheel(wheel)]
    if len(release_wheels) != 1:
        msg = f"Expected exactly 1 release wheel, found {len(release_wheels)}"
        raise SystemExit(msg)

    core_wheels = [wheel for wheel in wheels if wheel not in release_wheels]
    if len(core_wheels) != 6:
        msg = f"Expected 6 core wheels, found {len(core_wheels)}"
        raise SystemExit(msg)

    expected_norm = _normalize_version(expected_version)
    found_platforms: set[str] = set()
    for wheel in wheels:
        wheel_version = _wheel_version(wheel)
        if wheel_version is None:
            raise SystemExit(f"Could not parse version from wheel filename: {wheel.name}")
        if _normalize_version(wheel_version) != expected_norm:
            raise SystemExit(
                f"Version mismatch in {wheel.name}: expected {expected_version}, got {wheel_version}"
            )
        if wheel in core_wheels:
            platform_key = _platform_from_core_wheel(wheel)
            if platform_key is None:
                raise SystemExit(f"Unrecognized core wheel platform: {wheel.name}")
            found_platforms.add(platform_key)

    missing = set(SUPPORTED_PLATFORMS) - found_platforms
    if missing:
        raise SystemExit(f"Missing core wheels for platforms: {sorted(missing)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate harness PyPI upload wheel set")
    parser.add_argument("upload_dir", type=Path, help="Directory containing wheels to upload")
    parser.add_argument(
        "--version",
        default=None,
        help="Expected harness version (default: read from pyproject.toml)",
    )
    args = parser.parse_args()
    version = args.version or read_harness_version(_REPO_ROOT)
    validate_upload_dir(args.upload_dir, version)
    print(f"Validated 7 wheels for myrm-agent-harness {version} in {args.upload_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
