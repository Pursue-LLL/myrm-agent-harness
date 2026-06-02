#!/usr/bin/env python3
"""Assemble production harness wheels (core + release).

Usage::

    uv sync --group build
    .venv/bin/python scripts/assemble_production.py
    .venv/bin/python scripts/assemble_production.py --install ../myrm-agent-server
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from harness_packaging.assemble import (  # noqa: E402
    assemble_production_wheels,
    install_production_wheels,
    run_post_install_verify,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build production harness wheels")
    parser.add_argument(
        "--install",
        type=Path,
        default=None,
        help="Install wheels into venv at this project directory (e.g. myrm-agent-server)",
    )
    args = parser.parse_args()

    wheels = assemble_production_wheels()
    print(f"Core wheel:    {wheels.core_wheel}")
    print(f"Release wheel: {wheels.release_wheel}")

    if args.install is not None:
        venv_python = install_production_wheels(
            wheels.core_wheel,
            wheels.release_wheel,
            install_dir=args.install,
        )
        run_post_install_verify(venv_python)
        print("Production harness install verified")


if __name__ == "__main__":
    main()
