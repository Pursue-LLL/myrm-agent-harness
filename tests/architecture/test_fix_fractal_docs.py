"""Tests for scripts/fix_fractal_docs.py: the fixer must turn a red fractal-doc gate green, safely."""

from __future__ import annotations

import stat
import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_repo_root))

import scripts.fix_fractal_docs as fixer
from scripts.check_fractal_docs import FIX_HINT
from scripts.check_fractal_docs import main as fractal_gate_main
from scripts.validate_arch_inventory import DirReport, _format_reports

pytestmark = pytest.mark.architecture

_ENGINE = 'class AlphaEngine:\n    """Runs the alpha flow."""\n'
_WORKER = 'class BetaWorker:\n    """Works for beta."""\n'
_ROOT_ARCH = """# myrm_agent_harness/

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Root. | ✅ |

| Submodule | Description |
|-----------|-------------|
| alpha/ | Alpha package. See [alpha/_ARCH.md](alpha/_ARCH.md). |
"""
_ALPHA_ARCH = """# alpha/

| File | Role | Description | I/O/P |
|------|------|-------------|-------|
| `__init__.py` | Package | Alpha facade. | ✅ |
| `gone.py` | Core | Deleted long ago. | ✅ |
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _build(tmp_path: Path) -> Path:
    """Package with an undocumented module, a stale row, and a brand-new directory without ``_ARCH.md``."""
    package_root = tmp_path / "src" / "myrm_agent_harness"
    _write(package_root / "__init__.py", "")
    _write(package_root / "_ARCH.md", _ROOT_ARCH)
    _write(package_root / "alpha" / "__init__.py", "")
    _write(package_root / "alpha" / "engine.py", _ENGINE)
    _write(package_root / "alpha" / "_ARCH.md", _ALPHA_ARCH)
    _write(package_root / "beta" / "__init__.py", "")
    _write(package_root / "beta" / "worker.py", _WORKER)
    return package_root.resolve()


def _args(package_root: Path, *extra: str, baseline: str = "") -> list[str]:
    baseline_file = _write(package_root.parent.parent / "baseline.txt", baseline)
    return [*extra, "--package-root", str(package_root), "--header-baseline", str(baseline_file)]


def _snapshot(package_root: Path) -> dict[Path, bytes]:
    return {path: path.read_bytes() for path in package_root.rglob("*") if path.is_file()}


def _assert_gates_green(package_root: Path) -> None:
    assert fixer.gate.missing_io_headers(package_root) == []
    assert fixer.gate.missing_arch_dirs(package_root) == []
    assert [r for r in fixer.inventory.scan_tree(package_root) if r.missing_in_arch or r.extra_in_arch] == []


def test_dry_run_reports_everything_and_changes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    package_root = _build(tmp_path)
    before = _snapshot(package_root)

    code = fixer.main(_args(package_root))

    out = capsys.readouterr().out
    assert code == 1
    assert _snapshot(package_root) == before
    for expected in ("header  ", "table   ", "create  ", "index   ", "-gone.py", "+engine.py", "Dry run: 5 file(s)"):
        assert expected in out


def test_write_all_turns_the_gates_green_and_is_idempotent(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    package_root = _build(tmp_path)

    assert fixer.main(_args(package_root, "--write", "--all")) == 0

    _assert_gates_green(package_root)
    assert "| beta/ |" in (package_root / "_ARCH.md").read_text(encoding="utf-8")
    assert "| `worker.py` | Core | Works for beta. | ✅ |" in (package_root / "beta" / "_ARCH.md").read_text(
        encoding="utf-8"
    )
    assert list(package_root.rglob("*.fixtmp")) == []
    capsys.readouterr()
    assert fixer.main(_args(package_root)) == 0
    assert capsys.readouterr().out.strip() == "Nothing to fix."


def test_write_with_paths_touches_only_the_requested_files(tmp_path: Path) -> None:
    package_root = _build(tmp_path)
    engine = package_root / "alpha" / "engine.py"
    worker = package_root / "beta" / "worker.py"

    assert fixer.main(_args(package_root, "--write", str(engine))) == 0

    assert "[POS]\nRuns the alpha flow." in engine.read_text(encoding="utf-8")
    assert worker.read_text(encoding="utf-8") == _WORKER
    assert not (package_root / "beta" / "_ARCH.md").exists()
    arch = (package_root / "alpha" / "_ARCH.md").read_text(encoding="utf-8")
    assert "`engine.py`" in arch and "gone.py" not in arch


def test_write_needs_a_scope(tmp_path: Path) -> None:
    package_root = _build(tmp_path)
    before = _snapshot(package_root)

    with pytest.raises(SystemExit) as no_scope:
        fixer.main(_args(package_root, "--write"))
    with pytest.raises(SystemExit) as both:
        fixer.main(_args(package_root, "--write", "--all", str(package_root / "alpha")))
    with pytest.raises(SystemExit) as outside:
        fixer.main(_args(package_root, "--write", str(tmp_path / "elsewhere.py")))

    assert (no_scope.value.code, both.value.code, outside.value.code) == (2, 2, 2)
    assert _snapshot(package_root) == before


def test_header_baseline_entries_are_left_alone(tmp_path: Path) -> None:
    package_root = _build(tmp_path)
    engine = package_root / "alpha" / "engine.py"

    code = fixer.main(_args(package_root, "--write", "--all", baseline="myrm_agent_harness/alpha/engine.py\n"))

    assert code == 0
    assert engine.read_text(encoding="utf-8") == _ENGINE
    assert "`engine.py`" in (package_root / "alpha" / "_ARCH.md").read_text(encoding="utf-8")


def test_file_changed_between_analysis_and_write_is_not_overwritten(tmp_path: Path) -> None:
    package_root = _build(tmp_path)
    plan = fixer.build_plan(package_root, frozenset(), lambda _path: True)
    engine = package_root / "alpha" / "engine.py"
    concurrent = _ENGINE + "# edited by another session\n"
    engine.write_text(concurrent, encoding="utf-8")

    failures = fixer.apply_plan(plan)

    assert [path for path, _ in failures] == [engine]
    assert engine.read_text(encoding="utf-8") == concurrent
    assert "[POS]" in (package_root / "beta" / "worker.py").read_text(encoding="utf-8")


def test_unparseable_file_is_skipped_reported_and_never_modified(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    package_root = _build(tmp_path)
    broken = _write(package_root / "alpha" / "broken.py", "def broken(:\n")

    code = fixer.main(_args(package_root, "--write", "--all"))

    assert code == 1
    assert broken.read_text(encoding="utf-8") == "def broken(:\n"
    assert "skip    " in capsys.readouterr().out
    assert "[POS]" in (package_root / "alpha" / "engine.py").read_text(encoding="utf-8")


def test_file_permissions_survive_the_atomic_write(tmp_path: Path) -> None:
    package_root = _build(tmp_path)
    worker = package_root / "beta" / "worker.py"
    worker.chmod(0o755)

    fixer.main(_args(package_root, "--write", str(worker)))

    assert stat.S_IMODE(worker.stat().st_mode) == 0o755


def test_gates_point_failing_developers_to_the_fixer(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    package_root = _build(tmp_path)

    code = fractal_gate_main(["--package-root", str(package_root), "--strict-headers"])

    err = capsys.readouterr().err
    report = DirReport(tmp_path, ("a.py",), tmp_path / "_ARCH.md", frozenset(), ("a.py",), ())
    assert code != 0
    assert FIX_HINT in err and "fix_fractal_docs.py" in FIX_HINT
    assert "fix_fractal_docs.py" in _format_reports([report], root_label="demo")
    assert (_repo_root / "scripts" / "fix_fractal_docs.py").is_file()
