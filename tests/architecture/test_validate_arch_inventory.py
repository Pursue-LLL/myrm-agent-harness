"""Tests for scripts/validate_arch_inventory.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_repo_root))

from scripts.validate_arch_inventory import (  # noqa: E402
    _is_inventory_file_cell,
    _listed_py_in_arch,
    scan_directory,
)


@pytest.mark.architecture
def test_listed_py_ignores_prose_mentions(tmp_path: Path) -> None:
    arch = tmp_path / "_ARCH.md"
    arch.write_text(
        """# demo/

See server/stream_loop.py and stream_lane_factory.py for wiring.

| File | Role |
|------|------|
| `runner.py` | Core |
| `config.py` | Config |
""",
        encoding="utf-8",
    )
    assert _listed_py_in_arch(arch) == {"runner.py", "config.py"}


@pytest.mark.architecture
def test_listed_py_ignores_multi_file_comparison_cells(tmp_path: Path) -> None:
    arch = tmp_path / "_ARCH.md"
    arch.write_text(
        """| Allowed | Forbidden |
|---------|-----------|
| Root docs and package marker files (see note below) | Vendor packages |
| `_ARCH.md`, `SECURITY_WRAPPER_GUIDE.md`, `__init__.py` | Runtime/cache dirs |
""",
        encoding="utf-8",
    )
    assert _listed_py_in_arch(arch) == set()


@pytest.mark.architecture
def test_is_inventory_file_cell_rejects_prose_lists() -> None:
    assert not _is_inventory_file_cell("_ARCH.md`, `SECURITY_WRAPPER_GUIDE.md`, `__init__.py")
    assert _is_inventory_file_cell("dialog_manager.py")
    assert _is_inventory_file_cell("__init__.py")
    assert not _is_inventory_file_cell("api/hooks.py")


@pytest.mark.architecture
def test_scan_directory_detects_missing_and_extra(tmp_path: Path) -> None:
    (tmp_path / "listed.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "orphan.py").write_text("y = 2\n", encoding="utf-8")
    (tmp_path / "_ARCH.md").write_text(
        """| File | Role |
|------|------|
| `listed.py` | ok |
| `ghost.py` | stale |
""",
        encoding="utf-8",
    )
    report = scan_directory(tmp_path)
    assert report is not None
    assert report.missing_in_arch == ("orphan.py",)
    assert report.extra_in_arch == ("ghost.py",)


@pytest.mark.architecture
def test_middlewares_inventory_passes() -> None:
    middlewares = _repo_root / "src" / "myrm_agent_harness" / "agent" / "middlewares"
    report = scan_directory(middlewares)
    assert report is not None
    assert report.missing_in_arch == ()
    assert report.extra_in_arch == ()


@pytest.mark.architecture
def test_agent_arch_inventory_passes() -> None:
    import subprocess
    import sys

    agent_root = _repo_root / "src" / "myrm_agent_harness" / "agent"
    script = _repo_root / "scripts" / "validate_arch_inventory.py"
    result = subprocess.run(
        [sys.executable, str(script), "--root", str(agent_root)],
        cwd=_repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


@pytest.mark.architecture
def test_harness_arch_inventory_passes() -> None:
    import subprocess
    import sys

    harness_root = _repo_root / "src" / "myrm_agent_harness"
    script = _repo_root / "scripts" / "validate_arch_inventory.py"
    result = subprocess.run(
        [sys.executable, str(script), "--root", str(harness_root)],
        cwd=_repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
