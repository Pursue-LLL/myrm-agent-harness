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


def test_check_reports_baseline_overage(scratch: Path) -> None:
    """A baseline-listed file exceeding its cap must be reported."""
    from scripts.check_file_line_limit import check

    pkg = scratch / "src" / _REPO
    baseline = scratch / "file_line_baseline.txt"
    # ok.py has 3 lines and baseline cap 3 → shrink the cap to force an overage.
    baseline.write_text(f"{_REPO}/sub/ok.py\t2\n", encoding="utf-8")
    errors = check(pkg, baseline, max_lines=500, files=[pkg / "sub" / "ok.py"])
    assert len(errors) == 1
    assert "exceeds baseline cap 2" in errors[0]


def test_load_baseline_accepts_unlisted_default(scratch: Path) -> None:
    """A baseline line without a tab counts as cap+1 (unlisted default)."""
    from scripts.check_file_line_limit import _load_baseline

    baseline = scratch / "bare.txt"
    baseline.write_text(f"{_REPO}/sub/ok.py\n", encoding="utf-8")
    loaded = _load_baseline(baseline)
    assert loaded[f"{_REPO}/sub/ok.py"] == 501


def test_iter_py_files_skips_prune_dirs(scratch: Path) -> None:
    """Files under cache directories must be pruned from the scan."""
    from scripts.check_file_line_limit import _iter_py_files

    pkg = scratch / "src" / _REPO
    cache = pkg / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "cached.py").write_text("x = 1\n", encoding="utf-8")
    files = _iter_py_files(pkg)
    names = {p.name for p in files}
    assert "cached.py" not in names
    assert "ok.py" in names


def test_main_full_mode_ok(scratch: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """CLI full scan on a clean tree exits 0 with an OK line."""
    from scripts.check_file_line_limit import main

    pkg = scratch / "src" / _REPO
    baseline = scratch / "file_line_baseline.txt"
    # Build a clean tree: ok.py (3 lines) within its baseline cap only.
    for cached in pkg.rglob("big.py"):
        cached.unlink()
    rc = main(["--package-root", str(pkg), "--baseline", str(baseline)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK" in out


def test_main_full_mode_violation(
    scratch: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI full scan with a violating file exits 1 and prints the violation."""
    from scripts.check_file_line_limit import main

    pkg = scratch / "src" / _REPO
    baseline = scratch / "file_line_baseline.txt"
    (pkg / "sub" / "huge.py").write_text("a = 1\n" * 600, encoding="utf-8")
    rc = main(["--package-root", str(pkg), "--baseline", str(baseline)])
    err = capsys.readouterr().err
    assert rc == 1
    assert "File line limit violations" in err
    assert "huge.py" in err


def test_main_incremental_no_changes(
    scratch: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--incremental with an empty change set prints OK and exits 0."""
    from scripts.check_file_line_limit import main
    from scripts.boundary_engine import get_changed_harness_files

    pkg = scratch / "src" / _REPO
    baseline = scratch / "file_line_baseline.txt"

    def _no_changes(_root: Path) -> list[Path]:
        return []

    monkeypatch.setattr(
        "scripts.check_file_line_limit.get_changed_harness_files", _no_changes
    )
    rc = main(
        ["--package-root", str(pkg), "--baseline", str(baseline), "--incremental"]
    )
    out = capsys.readouterr().out
    assert rc == 0
    assert "no harness files changed" in out


def test_main_incremental_git_unavailable(
    scratch: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--incremental with git unavailable falls back to a full scan."""
    from scripts.check_file_line_limit import main

    pkg = scratch / "src" / _REPO
    baseline = scratch / "file_line_baseline.txt"
    for cached in pkg.rglob("big.py"):
        cached.unlink()

    monkeypatch.setattr(
        "scripts.check_file_line_limit.get_changed_harness_files",
        lambda _root: None,
    )
    rc = main(
        ["--package-root", str(pkg), "--baseline", str(baseline), "--incremental"]
    )
    assert rc == 0


def test_main_incremental_scoped_violation(
    scratch: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """--incremental reporting a scoped violation must exit 1."""
    from scripts.check_file_line_limit import main

    pkg = scratch / "src" / _REPO
    baseline = scratch / "file_line_baseline.txt"
    (pkg / "sub" / "huge.py").write_text("a = 1\n" * 600, encoding="utf-8")

    monkeypatch.setattr(
        "scripts.check_file_line_limit.get_changed_harness_files",
        lambda _root: [pkg / "sub" / "huge.py"],
    )
    rc = main(
        ["--package-root", str(pkg), "--baseline", str(baseline), "--incremental"]
    )
    err = capsys.readouterr().err
    assert rc == 1
    assert "huge.py" in err
