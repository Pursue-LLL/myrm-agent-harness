"""Tests for cleanup_context_files_local (synchronous cleanup by modification time)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from myrm_agent_harness.runtime.context.cleanup import CONTEXT_RETENTION_DAYS, cleanup_context_files_local
from myrm_agent_harness.runtime.paths import execution_paths

_DAY_S = 86400


@pytest.fixture
def context_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".context"
    root.mkdir()
    monkeypatch.setattr(execution_paths, "CONTEXT_ROOT", str(root))
    return root


def _create_aged_file(path: Path, age_days: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("content")
    stamp = time.time() - age_days * _DAY_S
    os.utime(path, (stamp, stamp))


def test_retention_window_defaults_to_fourteen_days() -> None:
    assert CONTEXT_RETENTION_DAYS == 14


def test_cleanup_local_no_context_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(execution_paths, "CONTEXT_ROOT", "/nonexistent")

    assert cleanup_context_files_local() == 0


def test_cleanup_local_removes_files_past_the_window(context_root: Path) -> None:
    stale = context_root / "chat_abc" / "compacted" / "old.txt"
    _create_aged_file(stale, age_days=30)

    assert cleanup_context_files_local() == 1
    assert not stale.exists()


def test_cleanup_local_keeps_files_inside_the_window(context_root: Path) -> None:
    kept = context_root / "chat_abc" / "compacted" / "recent.txt"
    _create_aged_file(kept, age_days=CONTEXT_RETENTION_DAYS - 1)

    assert cleanup_context_files_local() == 0
    assert kept.exists()


def test_cleanup_local_window_is_configurable(context_root: Path) -> None:
    file = context_root / "chat_abc" / "compacted" / "medium_age.txt"
    _create_aged_file(file, age_days=5)

    assert cleanup_context_files_local(retention_days=3) == 1
    assert not file.exists()


def test_cleanup_local_skips_system_dir(context_root: Path) -> None:
    system_file = context_root / "system" / "compacted" / "config.txt"
    _create_aged_file(system_file, age_days=100)

    assert cleanup_context_files_local() == 0
    assert system_file.exists()


def test_cleanup_local_scratchpad_files(context_root: Path) -> None:
    _create_aged_file(context_root / "chat_abc" / "scratchpad" / "notes.txt", age_days=30)

    assert cleanup_context_files_local() == 1
