"""Unit tests for the source-text assertion gate.

Targets the AST scanners: a test that reads a ``.py`` module and asserts a string
literal appears in it is flagged, while equivalent structural or non-Python
assertions are left alone.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "check_test_source_assertions",
    Path(__file__).resolve().parents[2] / "scripts/check_test_source_assertions.py",
)
assert _spec and _spec.loader
_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gate)


def _violations(body: str) -> list[tuple[int, str]]:
    return _gate._source_text_assertions(ast.parse(body), _gate._read_text_bindings(ast.parse(body)))


def test_flags_literal_asserted_against_read_python_source() -> None:
    body = """
from pathlib import Path

def test_x():
    source = Path("pkg/mod.py").read_text(encoding="utf-8")
    assert "def target" in source
"""
    assert _violations(body) == [(6, "def target")]


def test_flags_chained_path_expression() -> None:
    body = """
from pathlib import Path

def test_x():
    source = (Path(__file__).resolve().parents[3] / "src/pkg/mod.py").read_text()
    assert "call(" in source
"""
    assert len(_violations(body)) == 1


def test_ignores_non_python_source_reads() -> None:
    body = """
from pathlib import Path

def test_x():
    doc = Path("docs/guide.md").read_text(encoding="utf-8")
    assert "[Install](setup.md)" in doc
"""
    assert _violations(body) == []


def test_ignores_structural_ast_assertions() -> None:
    body = """
import ast
from pathlib import Path

def test_x():
    source = Path("pkg/mod.py").read_text(encoding="utf-8")
    calls = {ast.unparse(n) for n in ast.walk(ast.parse(source)) if isinstance(n, ast.Call)}
    assert "target()" in calls
"""
    assert _violations(body) == []


def test_ignores_unrelated_read_text_receiver() -> None:
    body = """
from pathlib import Path

def test_x():
    target = Path("pkg/mod.py")
    target.read_text(encoding="utf-8")
    assert "some literal" in target
"""
    assert _violations(body) == []


def test_reports_parse_error_without_crashing(tmp_path: Path) -> None:
    broken = tmp_path / "broken.py"
    broken.write_text("def (:\n", encoding="utf-8")
    assert _gate._scan(broken) == []


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("assert 1 == 1\n", 0),
        ("assert 'x' in ['x']\n", 0),
    ],
)
def test_non_source_text_asserts_pass(body: str, expected: int) -> None:
    assert len(_violations(body)) == expected
