#!/usr/bin/env python3
"""Reject tests that assert on raw source text.

A test that reads a module with ``Path(...).read_text()`` and then asserts that a
string literal appears in it breaks whenever a formatter re-wraps that call across
lines — the assertion is coupled to layout rather than to behaviour. Verify the
parsed syntax tree with ``ast`` instead, which no reformatting can invalidate.

Run (from myrm-agent-harness root)::

    uv run python scripts/check_test_source_assertions.py
    uv run python scripts/check_test_source_assertions.py --incremental

Exit codes:
    0  OK
    1  Source-text assertions found
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

_HARNESS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HARNESS_ROOT))

from scripts.boundary_engine import get_changed_harness_files  # noqa: E402

_TESTS_DIRNAME = "tests"


def _reads_python_source(node: ast.Call) -> bool:
    """True when the ``read_text()`` target path ends in ``.py``.

    Only Python modules are reformatted in a way that silently invalidates a text
    assertion; asserting on documentation or data files is a different concern.
    """
    for child in ast.walk(node.func.value):  # type: ignore[attr-defined]
        if isinstance(child, ast.Constant) and isinstance(child.value, str) and child.value.endswith(".py"):
            return True
    return False


def _read_text_bindings(tree: ast.AST) -> set[str]:
    """Names bound to a ``read_text()`` result, e.g. ``source = p.read_text()``.

    Covers both ``p.read_text()`` and the inline ``Path("mod.py").read_text()``
    form, since the variable holding the text is the assignment target either way.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        if not (isinstance(func, ast.Attribute) and func.attr == "read_text"):
            continue
        if not _reads_python_source(node.value):
            continue
        names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def _source_text_assertions(tree: ast.AST, bindings: set[str]) -> list[tuple[int, str]]:
    """``assert "<literal>" in <name>`` where ``<name>`` holds read source text."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare)):
            continue
        comparison = node.test
        if not (isinstance(comparison.left, ast.Constant) and isinstance(comparison.left.value, str)):
            continue
        if any(isinstance(c, ast.Name) and c.id in bindings for c in comparison.comparators):
            found.append((comparison.lineno, comparison.left.value.strip()[:60]))
    return found


def _scan(test_file: Path) -> list[tuple[int, str]]:
    try:
        tree = ast.parse(test_file.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        print(f"ERROR: cannot parse {test_file}: {exc}", file=sys.stderr)
        return []
    bindings = _read_text_bindings(tree)
    if not bindings:
        return []
    return _source_text_assertions(tree, bindings)


def _target_files(harness_root: Path, incremental: bool) -> list[Path]:
    if incremental:
        changed = get_changed_harness_files(harness_root / _TESTS_DIRNAME)
        if changed is not None:
            return sorted(changed)
    return sorted((harness_root / _TESTS_DIRNAME).rglob("*.py"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only check test files changed in git (for pre-commit hooks)",
    )
    args = parser.parse_args(argv)

    harness_root = Path(__file__).resolve().parent.parent
    violations: list[tuple[Path, int, str]] = []
    for test_file in _target_files(harness_root, args.incremental):
        violations.extend((test_file, line, text) for line, text in _scan(test_file))

    if violations:
        print("ERROR: tests asserting on raw source text (reformatting will break them):", file=sys.stderr)
        for test_file, line, text in violations:
            print(f"  - {test_file}:{line}  {text}", file=sys.stderr)
        print(
            "\nAssert against the parsed tree with `ast` instead, so the check is\nindependent of line wrapping.",
            file=sys.stderr,
        )
        return 1

    print("OK (no source-text assertions).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
