#!/usr/bin/env python3
"""Fractal self-documentation gate for myrm-agent-harness.

Reports directories under ``src/myrm_agent_harness/`` that contain ``*.py`` and are
missing ``_ARCH.md`` (pure data/config directories with only JSON/YAML/SQL are skipped),
and optionally flags Python modules that lack a file-header position marker.

Run (from myrm-agent-harness root)::

    uv run python scripts/check_fractal_docs.py
    uv run python scripts/check_fractal_docs.py --strict-headers

Exit codes:
    0  No missing _ARCH.md (and no strict header violations when enabled).
    1  Strict header check found violations.
    2  One or more directories missing _ARCH.md.
    3  Both directory and (strict) header violations.
    4  Stub marker found in guarded _ARCH.md paths (--no-stub).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterable
from pathlib import Path

_PRUNE_DIR_NAMES: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "node_modules",
        ".bin",
    }
)

_HEADER_SKIP_NAMES: frozenset[str] = frozenset({"__init__.py"})
_HEADER_MAX_SCAN_LINES = 120
_HEADER_PATTERN = re.compile(
    r"(?m)^\s*(\[POS\]|\[INPUT\]|@pos:|@input:)",
)
_STUB_MARKERS = ("待补", "（见目录）", "见源码")
_NO_STUB_PREFIXES = ("api/",)


def _is_pruned_dir(path: Path) -> bool:
    if path.name in _PRUNE_DIR_NAMES:
        return True
    return "node_modules" in path.parts


def _dir_requires_arch(directory: Path) -> bool:
    """Only Python module directories need _ARCH.md (doc.md L3)."""
    return any(directory.glob("*.py"))


def _iter_package_dirs(package_root: Path) -> Iterable[Path]:
    if not package_root.is_dir():
        return
    if _dir_requires_arch(package_root):
        yield package_root
    for path in sorted(package_root.rglob("*")):
        if not path.is_dir():
            continue
        if _is_pruned_dir(path):
            continue
        if not _dir_requires_arch(path):
            continue
        yield path


def _missing_arch_dirs(package_root: Path) -> list[Path]:
    missing: list[Path] = []
    for directory in _iter_package_dirs(package_root):
        arch = directory / "_ARCH.md"
        if not arch.is_file():
            missing.append(directory)
    return missing


def _should_skip_header_scan(rel: Path, content_len: int) -> bool:
    if rel.name in _HEADER_SKIP_NAMES and content_len <= 512:
        return True
    return False


def _load_header_baseline(path: Path) -> frozenset[str]:
    if not path.is_file():
        raise FileNotFoundError(f"Header baseline not found: {path}")
    entries: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        entries.add(stripped)
    return frozenset(entries)


def _rel_package_path(package_root: Path, py_file: Path) -> str:
    return str(py_file.relative_to(package_root.parent))


def _arch_has_stub(content: str) -> bool:
    return any(marker in content for marker in _STUB_MARKERS)


def _stub_arch_files(package_root: Path) -> list[Path]:
    bad: list[Path] = []
    for arch in sorted(package_root.rglob("_ARCH.md")):
        if any(part in _PRUNE_DIR_NAMES for part in arch.parts):
            continue
        rel = str(arch.parent.relative_to(package_root)).replace("\\", "/")
        if rel == ".":
            rel = ""
        if not any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in _NO_STUB_PREFIXES):
            continue
        text = arch.read_text(encoding="utf-8")
        if _arch_has_stub(text):
            bad.append(arch)
    return bad


def _missing_io_headers(package_root: Path) -> list[Path]:
    bad: list[Path] = []
    for py in sorted(package_root.rglob("*.py")):
        if any(part in _PRUNE_DIR_NAMES for part in py.parts) or "node_modules" in py.parts:
            continue
        raw = py.read_bytes()
        if _should_skip_header_scan(py.relative_to(package_root), len(raw)):
            continue
        text = raw.decode("utf-8", errors="replace")
        head = "\n".join(text.splitlines()[:_HEADER_MAX_SCAN_LINES])
        if not _HEADER_PATTERN.search(head):
            bad.append(py)
    return bad


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    default_root = Path(__file__).resolve().parent.parent / "src" / "myrm_agent_harness"
    parser.add_argument(
        "--package-root",
        type=Path,
        default=default_root,
        help="Path to the harness package (default: ../src/myrm_agent_harness).",
    )
    parser.add_argument(
        "--strict-headers",
        action="store_true",
        help="Fail if a non-trivial .py file lacks [POS]/[INPUT] or @pos:/@input: in the first lines.",
    )
    parser.add_argument(
        "--header-baseline",
        type=Path,
        default=None,
        help="With --strict-headers: allow listed package-relative paths (one per line).",
    )
    parser.add_argument(
        "--no-stub",
        action="store_true",
        help="Fail if guarded paths (api/) contain stub markers in _ARCH.md.",
    )
    args = parser.parse_args(argv)

    package_root: Path = args.package_root.resolve()
    missing_arch = _missing_arch_dirs(package_root)
    bad_headers: list[Path] = []
    if args.strict_headers:
        all_bad = _missing_io_headers(package_root)
        if args.header_baseline is not None:
            baseline = _load_header_baseline(args.header_baseline.resolve())
            bad_headers = [file for file in all_bad if _rel_package_path(package_root, file) not in baseline]
        else:
            bad_headers = all_bad

    stub_arch: list[Path] = []
    if args.no_stub:
        stub_arch = _stub_arch_files(package_root)

    if missing_arch:
        print("ERROR: Directories missing _ARCH.md:", file=sys.stderr)
        for directory in missing_arch:
            print(f"  - {directory.relative_to(package_root.parent.parent)}", file=sys.stderr)

    if args.strict_headers and bad_headers:
        print("ERROR: Python files missing fractal header markers:", file=sys.stderr)
        for file in bad_headers:
            print(f"  - {file.relative_to(package_root.parent.parent)}", file=sys.stderr)

    if stub_arch:
        print("ERROR: _ARCH.md stub markers in guarded paths (api/):", file=sys.stderr)
        for arch in stub_arch:
            print(f"  - {arch.relative_to(package_root.parent.parent)}", file=sys.stderr)

    if not missing_arch and not bad_headers and not stub_arch:
        scope = "directory _ARCH.md"
        if args.strict_headers:
            scope += " + strict file headers"
        if args.no_stub:
            scope += " + no stub in api/"
        print(f"OK ({scope}).")
        return 0

    code = 0
    if missing_arch:
        code |= 2
    if bad_headers:
        code |= 1
    if stub_arch:
        code |= 4
    return code


if __name__ == "__main__":
    raise SystemExit(main())
