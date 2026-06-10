"""Checkpointer factory mode validation and fail-fast behavior."""

from pathlib import Path

import pytest

from myrm_agent_harness.runtime.checkpointing.factory import create_checkpointer


@pytest.mark.asyncio
async def test_unsupported_checkpointer_mode_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported checkpointer mode"):
        await create_checkpointer(mode="postgres")


@pytest.mark.asyncio
async def test_memory_mode_returns_memory_saver() -> None:
    saver, cleanup = await create_checkpointer(mode="memory")
    from langgraph.checkpoint.memory import MemorySaver

    assert isinstance(saver, MemorySaver)
    await cleanup()


@pytest.mark.asyncio
async def test_sqlite_mode_succeeds_on_temp_path(tmp_path: Path) -> None:
    db_path = tmp_path / "checkpoints" / "test.db"
    saver, cleanup = await create_checkpointer(mode="sqlite", sqlite_db_path=str(db_path))
    try:
        assert saver is not None
        assert db_path.is_file()
    finally:
        await cleanup()


@pytest.mark.asyncio
async def test_sqlite_mode_raises_when_path_not_writable(tmp_path: Path) -> None:
    db_file = tmp_path / "readonly.db"
    db_file.write_text("block", encoding="utf-8")
    db_file.chmod(0o444)

    with pytest.raises(RuntimeError, match="Failed to initialize SQLite checkpointer"):
        await create_checkpointer(mode="sqlite", sqlite_db_path=str(db_file))


@pytest.mark.asyncio
async def test_sqlite_mode_raises_when_sqlite_package_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys

    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.sqlite", None)
    monkeypatch.setitem(sys.modules, "langgraph.checkpoint.sqlite.aio", None)

    with pytest.raises(ImportError, match="langgraph-checkpoint-sqlite"):
        await create_checkpointer(mode="sqlite", sqlite_db_path=":memory:")
