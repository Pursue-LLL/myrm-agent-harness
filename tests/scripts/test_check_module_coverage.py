"""Unit tests for the per-module coverage floor gate.

Targets the CLI against a synthetic coverage data file so the floor comparison
can be exercised without running the unit suite.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "check_module_coverage",
    Path(__file__).resolve().parents[2] / "scripts/check_module_coverage.py",
)
assert _spec and _spec.loader
_gate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_gate)


@pytest.fixture()
def data_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Coverage data measuring one module at 100% and one at 50%."""
    from coverage import CoverageData

    covered = tmp_path / "covered.py"
    covered.write_text("a = 1\nb = 2\nif a:\n    b = 3\n", encoding="utf-8")
    half = tmp_path / "half.py"
    half.write_text("a = 1\nb = 2\nc = 3\nd = 4\n", encoding="utf-8")

    data = CoverageData(basename=str(tmp_path / ".coverage"))
    data.add_lines({str(covered): {1, 2, 3, 4}})
    data.add_lines({str(half): {1, 2}})
    data.write()

    monkeypatch.setattr(
        _gate,
        "COVERAGE_FLOORS",
        {f"*/{covered.name}": 90.0, f"*/{half.name}": 90.0},
    )
    return tmp_path / ".coverage"


def test_fails_a_module_below_floor(data_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _gate.main(["--data", str(data_file)]) == 1
    err = capsys.readouterr().err
    assert "below their coverage floor" in err
    assert "half.py" in err


def test_passes_when_all_floors_met(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from coverage import CoverageData

    module = tmp_path / "ok.py"
    module.write_text("a = 1\nb = 2\n", encoding="utf-8")
    data = CoverageData(basename=str(tmp_path / ".coverage"))
    data.add_lines({str(module): {1, 2}})
    data.write()
    monkeypatch.setattr(_gate, "COVERAGE_FLOORS", {f"*/{module.name}": 90.0})

    assert _gate.main(["--data", str(tmp_path / ".coverage")]) == 0
    assert "floor(s) met" in capsys.readouterr().out


def test_reports_unmeasured_module_as_violation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from coverage import CoverageData

    module = tmp_path / "seen.py"
    module.write_text("a = 1\n", encoding="utf-8")
    data = CoverageData(basename=str(tmp_path / ".coverage"))
    data.add_lines({str(module): {1}})
    data.write()
    monkeypatch.setattr(
        _gate,
        "COVERAGE_FLOORS",
        {f"*/{module.name}": 90.0, "*/never_measured.py": 90.0},
    )

    assert _gate.main(["--data", str(tmp_path / ".coverage")]) == 1
    assert "unmeasured" in capsys.readouterr().err


def test_missing_data_file_exits_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert _gate.main(["--data", str(tmp_path / "absent")]) == 1
    assert "coverage data not found" in capsys.readouterr().err
