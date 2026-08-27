"""Unit tests for FileSystemStrategyFactory."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.strategies.mcp_strategy import (
    MCPFileSystemStrategy,
)
from myrm_agent_harness.agent.meta_tools.file_ops.strategies.storage_strategy import (
    StorageBackendStrategy,
)
from myrm_agent_harness.agent.meta_tools.file_ops.strategies.strategy_factory import (
    FileSystemStrategyFactory,
)
from myrm_agent_harness.toolkits.code_execution.executors.base import (
    reset_executor,
    set_executor,
)


def test_create_strategy_mcp_path() -> None:
    strategy = FileSystemStrategyFactory.create_strategy("/mcp/some_skill/doc.md", [])
    assert isinstance(strategy, MCPFileSystemStrategy)


def test_create_strategy_with_explicit_executor() -> None:
    mock_executor = MagicMock()
    strategy = FileSystemStrategyFactory.create_strategy("some/file.py", [], executor=mock_executor)
    assert isinstance(strategy, StorageBackendStrategy)


def test_create_strategy_with_contextvar_executor() -> None:
    mock_executor = MagicMock()
    token = set_executor(mock_executor)
    try:
        strategy = FileSystemStrategyFactory.create_strategy("some/file.py", [])
        assert isinstance(strategy, StorageBackendStrategy)
    finally:
        reset_executor(token)


def test_create_strategy_with_storage_backend() -> None:
    mock_backend = MagicMock()
    strategy = FileSystemStrategyFactory.create_strategy("some/file.py", [], storage_backend=mock_backend)
    assert isinstance(strategy, StorageBackendStrategy)
    assert strategy.storage is mock_backend


def test_create_strategy_no_executor_raises() -> None:
    token = set_executor(None)
    try:
        with pytest.raises(ValueError, match="executor or storage_backend is required"):
            FileSystemStrategyFactory.create_strategy("some/file.py", [])
    finally:
        reset_executor(token)
