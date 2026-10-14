"""Tests for StorageBackendStrategy.replace_text delegation to batch engine."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.strategies.storage_strategy import (
    StorageBackendStrategy,
)
from myrm_agent_harness.toolkits.storage import LocalStorageBackend


@pytest.mark.asyncio
async def test_strategy_round_trips_through_local_storage_backend(tmp_path: Path) -> None:
    strategy = StorageBackendStrategy(LocalStorageBackend(tmp_path))

    await strategy.write_file("notes/a.txt", "hello world")
    await strategy.replace_text("notes/a.txt", "world", "there")

    assert await strategy.read_file("notes/a.txt") == ["hello there"]
    assert await strategy.get_file_size("notes/a.txt") == len("hello there")


@pytest.mark.asyncio
async def test_replace_text_delegates_to_batch_engine() -> None:
    storage = AsyncMock()
    storage.exists = AsyncMock(return_value=True)
    storage.read_text = AsyncMock(return_value="hello world")
    storage.write_text = AsyncMock()

    strategy = StorageBackendStrategy(storage)
    await strategy.replace_text("f.txt", "world", "there")

    storage.write_text.assert_awaited_once_with("f.txt", "hello there")


@pytest.mark.asyncio
async def test_replace_text_maps_batch_error_with_path() -> None:
    storage = AsyncMock()
    storage.exists = AsyncMock(return_value=True)
    storage.read_text = AsyncMock(return_value="content")
    storage.write_text = AsyncMock()

    strategy = StorageBackendStrategy(storage)
    with pytest.raises(ValueError, match=r"Text not found in file: f\.txt"):
        await strategy.replace_text("f.txt", "missing", "x")


@pytest.mark.asyncio
async def test_replace_text_file_missing() -> None:
    storage = AsyncMock()
    storage.exists = AsyncMock(return_value=False)

    strategy = StorageBackendStrategy(storage)
    with pytest.raises(FileNotFoundError, match="File not found"):
        await strategy.replace_text("f.txt", "a", "b")


@pytest.mark.asyncio
async def test_replace_text_logs_fuzzy_strategy() -> None:
    storage = AsyncMock()
    storage.exists = AsyncMock(return_value=True)
    storage.read_text = AsyncMock(return_value="  line1\n  line2\n")
    storage.write_text = AsyncMock()

    fuzzy_result = MagicMock()
    fuzzy_result.success = True
    fuzzy_result.content = "  line1\n  replaced\n"
    fuzzy_result.strategy = "indent_flexible"
    fuzzy_result.confidence = 0.9

    strategy = StorageBackendStrategy(storage)
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.core.batch_str_replace.fuzzy_replace",
        return_value=fuzzy_result,
    ):
        await strategy.replace_text("f.txt", "line2_typo", "replaced")

    written = storage.write_text.call_args[0][1]
    assert "replaced" in written
