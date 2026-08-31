#!/usr/bin/env python3
"""Validate Python package roots follow flat-layout rules (rule 5.1–5.3).

Package roots may only contain:
- __init__.py, client.py (SDK facade), py.typed (markers)
- _ARCH.md (module architecture doc)
- subdirectories (domain subpackages)

Any other ``.py`` at the package root is a violation.

Usage:
    python scripts/check_package_root_layout.py
    python scripts/check_package_root_layout.py --root src/myrm_agent_harness
    python scripts/check_package_root_layout.py --json

Exit codes:
    0: All checked package roots compliant
    1: Violations detected
    2: Internal error
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ROOT = _REPO_ROOT / "src" / "myrm_agent_harness"

_ALLOWED_ROOT_PY = frozenset({"__init__.py", "client.py", "py.typed"})

_FORBIDDEN_LEGACY_FLAT = (
    "_distribution.py",
    "_runtime_platform.py",
    "_core_ip_manifest.py",
    "_verify_distribution.py",
)


@dataclass(frozen=True)
class RootViolation:
    package_root: Path
    forbidden_files: tuple[str, ...]


def _is_package_root(directory: Path) -> bool:
    return (directory / "__init__.py").is_file()


def scan_package_root(package_root: Path) -> RootViolation | None:
    forbidden = sorted(
        p.name
        for p in package_root.iterdir()
        if p.is_file() and p.suffix == ".py" and p.name not in _ALLOWED_ROOT_PY
    )
    if not forbidden:
        return None
    return RootViolation(package_root=package_root, forbidden_files=tuple(forbidden))


def scan_tree(root: Path) -> list[RootViolation]:
    """Check the package root and designated inner package roots (e.g. runtime/)."""
    violations: list[RootViolation] = []
    if not root.is_dir():
        return violations
    if _is_package_root(root):
        hit = scan_package_root(root)
        if hit is not None:
            violations.append(hit)
    runtime_root = root / "runtime"
    if runtime_root.is_dir() and _is_package_root(runtime_root):
        hit = scan_package_root(runtime_root)
        if hit is not None:
            violations.append(hit)
    return violations


def scan_legacy_flat(package_root: Path) -> list[str]:
    return [name for name in _FORBIDDEN_LEGACY_FLAT if (package_root / name).is_file()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check Python package root flat-layout rules."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=_DEFAULT_ROOT,
        help="Top-level package directory to scan (default: src/myrm_agent_harness)",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    violations = scan_tree(root)
    legacy = scan_legacy_flat(root)

    if args.json:
        payload = {
            "root": str(root),
            "violations": [
                {
                    "package_root": str(v.package_root),
                    "forbidden_files": list(v.forbidden_files),
                }
                for v in violations
            ],
            "legacy_flat_files": legacy,
        }
        print(json.dumps(payload, indent=2))
        return 1 if violations or legacy else 0

    if legacy:
        for name in legacy:
            print(f"LEGACY_FLAT: {root / name}", file=sys.stderr)
    for v in violations:
        rel = v.package_root.relative_to(root) if v.package_root != root else Path(".")
        print(
            f"PACKAGE_ROOT_FLAT: {rel} has forbidden .py: {', '.join(v.forbidden_files)}",
            file=sys.stderr,
        )

    if violations or legacy:
        print(
            "Package root layout violations detected. "
            "Move implementation modules into domain subpackages; "
            "keep only __init__.py and client.py at package roots.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
