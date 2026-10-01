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


def test_target_files_falls_back_to_full_scan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "a.py").write_text("assert True\n", encoding="utf-8")
    (tests / "nested").mkdir()
    (tests / "nested" / "b.py").write_text("assert True\n", encoding="utf-8")

    monkeypatch.setattr(_gate, "get_changed_harness_files", lambda _root: None)

    assert _gate._target_files(tmp_path, incremental=True) == [
        tests / "a.py",
        tests / "nested" / "b.py",
    ]
    assert _gate._target_files(tmp_path, incremental=False) == [
        tests / "a.py",
        tests / "nested" / "b.py",
    ]


def test_target_files_uses_git_changed_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "a.py").write_text("assert True\n", encoding="utf-8")
    (tests / "b.py").write_text("assert True\n", encoding="utf-8")
    monkeypatch.setattr(_gate, "get_changed_harness_files", lambda _root: [tests / "b.py"])

    assert _gate._target_files(tmp_path, incremental=True) == [tests / "b.py"]


_CLEAN_TEST = "def test_x():\n    assert True\n"
_DIRTY_TEST = (
    "from pathlib import Path\n\n\ndef test_x():\n"
    '    src = Path("pkg/mod.py").read_text()\n'
    '    assert "needle" in src\n'
)


def _with_tests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str, name: str = "sample.py") -> None:
    tests = tmp_path / "tests"
    tests.mkdir(exist_ok=True)
    (tests / name).write_text(body, encoding="utf-8")
    monkeypatch.setattr(_gate, "_target_files", lambda *_args, **_kwargs: [tests / name])


def test_main_passes_when_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _with_tests(tmp_path, monkeypatch, _CLEAN_TEST)

    assert _gate.main([]) == 0
    assert "no source-text assertions" in capsys.readouterr().out


def test_main_reports_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _with_tests(tmp_path, monkeypatch, _DIRTY_TEST)

    assert _gate.main([]) == 1
    err = capsys.readouterr().err
    assert "raw source text" in err
    assert "needle" in err
    assert "ast" in err


def test_main_accepts_incremental_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = tmp_path / "tests" / "sample.py"
    _with_tests(tmp_path, monkeypatch, _CLEAN_TEST)
    seen: list[bool] = []

    def _record(_root: Path, incremental: bool) -> list[Path]:
        seen.append(incremental)
        return [sample]

    monkeypatch.setattr(_gate, "_target_files", _record)

    assert _gate.main(["--incremental"]) == 0
    assert seen == [True]
