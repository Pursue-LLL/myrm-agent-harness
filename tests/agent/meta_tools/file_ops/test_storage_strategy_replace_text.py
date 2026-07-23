"""Tests for StorageBackendStrategy.replace_text delegation to batch engine."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.strategies.storage_strategy import (
    StorageBackendStrategy,
)


@pytest.mark.asyncio
async def test_replace_text_delegates_to_batch_engine() -> None:
    storage = AsyncMock()
    storage.exists = AsyncMock(return_value=True)
    storage.get_text = AsyncMock(return_value="hello world")
    storage.put_text = AsyncMock()

    strategy = StorageBackendStrategy(storage)
    await strategy.replace_text("f.txt", "world", "there")

    storage.put_text.assert_awaited_once_with("f.txt", "hello there")


@pytest.mark.asyncio
async def test_replace_text_maps_batch_error_with_path() -> None:
    storage = AsyncMock()
    storage.exists = AsyncMock(return_value=True)
    storage.get_text = AsyncMock(return_value="content")
    storage.put_text = AsyncMock()

    strategy = StorageBackendStrategy(storage)
    with pytest.raises(ValueError, match="Text not found in file: f.txt"):
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
    storage.get_text = AsyncMock(return_value="  line1\n  line2\n")
    storage.put_text = AsyncMock()

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

    written = storage.put_text.call_args[0][1]
    assert "replaced" in written
