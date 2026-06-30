"""Tests for scripts/validate_arch_inventory.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_repo_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_repo_root))

from scripts.validate_arch_inventory import (  # noqa: E402
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
