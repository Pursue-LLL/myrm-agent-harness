"""Unit tests for the check_file_line_limit gate's incremental scope.

Targets the pure ``check()`` function: passing an explicit file list must
restrict validation to those files, mirroring pre-commit's --incremental mode.
Full-scan behaviour is covered by the architecture gate
(``tests/architecture/test_file_line_limit.py``) which invokes the CLI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
_REPO = _repo_root.name


@pytest.fixture()
def scratch(tmp_path: Path) -> Path:
    """Fake package root: src/<repo>/<sub>/x.py with a tiny baseline."""
    pkg = tmp_path / "src" / _REPO
    sub = pkg / "sub"
    sub.mkdir(parents=True)
    (sub / "ok.py").write_text("a = 1\nb = 2\nc = 3\n", encoding="utf-8")
    (sub / "big.py").write_text("a = 1\n" * 600, encoding="utf-8")
    baseline = tmp_path / "file_line_baseline.txt"
    baseline.write_text(f"{_REPO}/sub/ok.py\t3\n", encoding="utf-8")
    return tmp_path


def test_check_full_scans_all_files(scratch: Path) -> None:
    from scripts.check_file_line_limit import check

    pkg = scratch / "src" / _REPO
    baseline = scratch / "file_line_baseline.txt"
    errors = check(pkg, baseline, max_lines=500)
    assert len(errors) == 1
    assert "big.py" in errors[0] and "not in baseline" in errors[0]


def test_check_incremental_scope_skips_unchanged_files(scratch: Path) -> None:
    from scripts.check_file_line_limit import check

    pkg = scratch / "src" / _REPO
    baseline = scratch / "file_line_baseline.txt"
    # Only ok.py is in scope: within its baseline cap, so no violations.
    errors = check(pkg, baseline, max_lines=500, files=[pkg / "sub" / "ok.py"])
    assert errors == []


def test_check_incremental_catches_only_scoped_violation(scratch: Path) -> None:
    from scripts.check_file_line_limit import check

    pkg = scratch / "src" / _REPO
    baseline = scratch / "file_line_baseline.txt"
    errors = check(pkg, baseline, max_lines=500, files=[pkg / "sub" / "big.py"])
    assert len(errors) == 1
    assert "big.py" in errors[0]


def test_check_ignores_missing_files(scratch: Path) -> None:
    from scripts.check_file_line_limit import check

    pkg = scratch / "src" / _REPO
    baseline = scratch / "file_line_baseline.txt"
    errors = check(pkg, baseline, max_lines=500, files=[pkg / "sub" / "ghost.py"])
    assert errors == []
