#!/usr/bin/env python3
"""Verify all harness PyPI packages exist after upload.

[INPUT]
- harness_packaging.platforms::PUBLISH_PLATFORMS (POS: active PyPI publish platform set)
- harness_packaging.pypi_index::pypi_package_exists (POS: PyPI index probe helpers)
- harness_packaging.pypi_index::release_has_compiled_core_extra (POS: PyPI index probe helpers)
- harness_packaging.version::read_harness_version (POS: harness version reader)

[OUTPUT]
- main(): exit 0 when release + core packages are indexed and release exposes compiled-core extra

[POS]
Post-upload gate in publish-pypi.yml; prevents partial publishes from going green (release + 8 core wheels).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from harness_packaging.platforms import PYPI_VERIFY_PLATFORMS  # noqa: E402
from harness_packaging.pypi_index import (  # noqa: E402
    pypi_package_exists,
    release_has_compiled_core_extra,
)
from harness_packaging.version import read_harness_version  # noqa: E402

_USER_AGENT = "myrm-verify-pypi-publish"


def _expected_packages() -> tuple[str, ...]:
    core_packages = tuple(f"myrm-agent-harness-core-{platform_key}" for platform_key in PYPI_VERIFY_PLATFORMS)
    return ("myrm-agent-harness", *core_packages)


def missing_packages(version: str) -> list[str]:
    missing: list[str] = []
    for package in _expected_packages():
        if not pypi_package_exists(package, version, user_agent=_USER_AGENT):
            missing.append(f"{package}=={version}")
    if not release_has_compiled_core_extra(version, user_agent=_USER_AGENT):
        missing.append(f"myrm-agent-harness=={version} missing [compiled-core] extra metadata")
    return missing


def verify_published(version: str, *, max_attempts: int, delay_seconds: float) -> None:
    """Poll PyPI until all expected packages are indexed or fail."""
    expected_count = len(_expected_packages())
    for attempt in range(1, max_attempts + 1):
        missing = missing_packages(version)
        if not missing:
            print(
                f"PyPI publish verified: {expected_count} packages for myrm-agent-harness {version}"
            )
            return
        if attempt < max_attempts:
            print(
                f"PyPI index incomplete (attempt {attempt}/{max_attempts}): {', '.join(missing)}",
                file=sys.stderr,
            )
            time.sleep(delay_seconds)
            continue
        msg = "PyPI publish incomplete after upload: " + ", ".join(missing)
        raise SystemExit(msg)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify harness packages on PyPI after upload")
    parser.add_argument(
        "--version",
        default=None,
        help="Expected harness version (default: read from pyproject.toml)",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=12,
        help="PyPI index poll attempts (default: 12)",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=10.0,
        help="Seconds between poll attempts (default: 10)",
    )
    args = parser.parse_args()
    version = args.version or read_harness_version(_REPO_ROOT)
    verify_published(version, max_attempts=args.max_attempts, delay_seconds=args.delay_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
