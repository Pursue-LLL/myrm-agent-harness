"""Tests for cleanup_context_files_local (synchronous cleanup)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from myrm_agent_harness.runtime.context.cleanup import cleanup_context_files_local


@pytest.fixture
def context_root(tmp_path: Path) -> Path:
    root = tmp_path / ".context"
    root.mkdir()
    return root


def _create_old_file(path: Path, age_seconds: float = 100) -> None:
    path.write_text("content")
    old_time = time.time() - age_seconds
    os.utime(path, (old_time, old_time))


def test_cleanup_local_no_context_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", "/nonexistent")
    result = cleanup_context_files_local()
    assert result == 0


def test_cleanup_local_removes_old_files(context_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", str(context_root))

    session_dir = context_root / "chat_abc" / "compacted"
    session_dir.mkdir(parents=True)

    old_file = session_dir / "old.txt"
    _create_old_file(old_file, age_seconds=86400 * 30)

    removed = cleanup_context_files_local(max_age_days=7, file_access_days=14)
    assert removed == 1
    assert not old_file.exists()


def test_cleanup_local_keeps_recent_files(context_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", str(context_root))

    session_dir = context_root / "chat_abc" / "compacted"
    session_dir.mkdir(parents=True)

    recent_file = session_dir / "recent.txt"
    recent_file.write_text("content")

    removed = cleanup_context_files_local(max_age_days=7, file_access_days=14)
    assert removed == 0
    assert recent_file.exists()


def test_cleanup_local_skips_system_dir(context_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", str(context_root))

    system_dir = context_root / "system" / "compacted"
    system_dir.mkdir(parents=True)
    system_file = system_dir / "config.txt"
    _create_old_file(system_file, age_seconds=86400 * 100)

    removed = cleanup_context_files_local(max_age_days=7, file_access_days=14)
    assert removed == 0
    assert system_file.exists()


def test_cleanup_local_scratchpad_files(context_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", str(context_root))

    session_dir = context_root / "chat_abc" / "scratchpad"
    session_dir.mkdir(parents=True)

    old_file = session_dir / "notes.txt"
    _create_old_file(old_file, age_seconds=86400 * 30)

    removed = cleanup_context_files_local(max_age_days=7, file_access_days=14)
    assert removed == 1


def test_cleanup_local_mtime_fallback_protection(context_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """File within max_age_days but beyond file_access_days is kept by fallback."""
    monkeypatch.setattr("myrm_agent_harness.runtime.execution_paths.CONTEXT_ROOT", str(context_root))

    session_dir = context_root / "chat_abc" / "compacted"
    session_dir.mkdir(parents=True)

    file = session_dir / "medium_age.txt"
    _create_old_file(file, age_seconds=86400 * 5)

    removed = cleanup_context_files_local(max_age_days=7, file_access_days=3)
    assert removed == 0
    assert file.exists()
