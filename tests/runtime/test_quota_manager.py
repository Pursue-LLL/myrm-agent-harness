"""Tests for storage quota manager."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.runtime.quota.manager import SimpleStorageQuotaManager


@pytest.fixture
def context_root(tmp_path: Path) -> Path:
    root = tmp_path / ".context"
    root.mkdir()
    return root


@pytest.fixture
def manager(context_root: Path) -> SimpleStorageQuotaManager:
    return SimpleStorageQuotaManager(
        per_session_limit=1024 * 1024,  # 1MB
        auto_cleanup_threshold=0.8,
        context_root=str(context_root),
    )


def _create_session_files(context_root: Path, session_id: str, num_files: int = 3, file_size: int = 100) -> list[Path]:
    session_dir = context_root / session_id / "compacted"
    session_dir.mkdir(parents=True, exist_ok=True)
    files = []
    for i in range(num_files):
        f = session_dir / f"file_{i}.txt"
        f.write_text("x" * file_size)
        files.append(f)
    return files


@pytest.mark.asyncio
async def test_check_write_allowed_within_quota(manager: SimpleStorageQuotaManager, context_root: Path) -> None:
    _create_session_files(context_root, "session_a", num_files=1, file_size=100)
    allowed = await manager.check_write_allowed("session_a", 1024)
    assert allowed is True


@pytest.mark.asyncio
async def test_check_write_rejected_over_quota(manager: SimpleStorageQuotaManager, context_root: Path) -> None:
    _create_session_files(context_root, "session_a", num_files=1, file_size=100)
    allowed = await manager.check_write_allowed("session_a", 2 * 1024 * 1024)
    assert allowed is False


@pytest.mark.asyncio
async def test_auto_cleanup_triggered(manager: SimpleStorageQuotaManager, context_root: Path) -> None:
    _create_session_files(context_root, "session_a", num_files=20, file_size=50000)

    allowed = await manager.check_write_allowed("session_a", 100)
    assert allowed is True


@pytest.mark.asyncio
async def test_get_remaining_quota(manager: SimpleStorageQuotaManager, context_root: Path) -> None:
    _create_session_files(context_root, "session_a", num_files=1, file_size=100)
    remaining = await manager.get_remaining_quota("session_a")
    assert remaining > 0
    assert remaining == 1024 * 1024 - 100


@pytest.mark.asyncio
async def test_get_remaining_quota_empty_session(
    manager: SimpleStorageQuotaManager,
) -> None:
    remaining = await manager.get_remaining_quota("nonexistent")
    assert remaining == 1024 * 1024


@pytest.mark.asyncio
async def test_usage_cache_invalidation(manager: SimpleStorageQuotaManager, context_root: Path) -> None:
    _create_session_files(context_root, "session_a", num_files=1, file_size=100)
    await manager._get_session_usage("session_a")
    assert "session_a" in manager._usage_cache

    manager.invalidate_cache("session_a")
    assert "session_a" not in manager._usage_cache


@pytest.mark.asyncio
async def test_usage_cache_invalidation_all(manager: SimpleStorageQuotaManager, context_root: Path) -> None:
    _create_session_files(context_root, "session_a", num_files=1, file_size=100)
    _create_session_files(context_root, "session_b", num_files=1, file_size=100)
    await manager._get_session_usage("session_a")
    await manager._get_session_usage("session_b")

    manager.invalidate_cache()
    assert len(manager._usage_cache) == 0


@pytest.mark.asyncio
async def test_auto_cleanup_removes_oldest_files(manager: SimpleStorageQuotaManager, context_root: Path) -> None:
    import time

    session_dir = context_root / "session_a" / "compacted"
    session_dir.mkdir(parents=True)

    old_file = session_dir / "old_file.txt"
    old_file.write_text("x" * 200000)

    time.sleep(0.05)

    new_file = session_dir / "new_file.txt"
    new_file.write_text("y" * 200000)

    manager._per_session_limit = 300000
    manager._auto_cleanup_threshold = 0.5

    removed = await manager._auto_cleanup_session("session_a", target_ratio=0.3)

    assert removed >= 1


@pytest.mark.asyncio
async def test_auto_cleanup_empty_session(
    manager: SimpleStorageQuotaManager,
) -> None:
    removed = await manager._auto_cleanup_session("nonexistent")
    assert removed == 0


@pytest.mark.asyncio
async def test_scratchpad_files_counted(manager: SimpleStorageQuotaManager, context_root: Path) -> None:
    session_dir = context_root / "session_a" / "scratchpad"
    session_dir.mkdir(parents=True)
    f = session_dir / "notes.txt"
    f.write_text("x" * 500)

    usage = await manager._get_session_usage("session_a")
    assert usage == 500
