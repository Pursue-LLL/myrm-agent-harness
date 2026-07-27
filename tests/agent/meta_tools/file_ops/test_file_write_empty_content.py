"""Unit tests for file_write_tool empty content rejection and error mapping."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.meta_tools.file_ops.file_write_tool import (
    create_file_write_tool,
)
from myrm_agent_harness.utils.errors import ToolError

_DUMMY_CONFIG = RunnableConfig()


@pytest.mark.asyncio
@pytest.mark.parametrize("empty_content", ["", "   ", "\n\t  \n"])
async def test_file_write_rejects_empty_content(empty_content: str) -> None:
    tool = create_file_write_tool()

    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_write_tool.ensure_executor",
        ) as mock_ensure,
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_write_tool.FileOperationService",
        ) as mock_service_cls,
        pytest.raises(ToolError) as exc_info,
    ):
        await tool.ainvoke(
            {"path": "reports/week.md", "content": empty_content},
            config=_DUMMY_CONFIG,
        )

    assert "empty" in str(exc_info.value.user_hint).lower()
    mock_ensure.assert_not_called()
    mock_service_cls.assert_not_called()


@pytest.mark.asyncio
async def test_file_write_rejects_oversized_content() -> None:
    tool = create_file_write_tool()

    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_write_tool.MAX_FILE_WRITE_SIZE_BYTES",
            8,
        ),
        pytest.raises(ToolError) as exc_info,
    ):
        await tool.ainvoke(
            {"path": "big.txt", "content": "0123456789"},
            config=_DUMMY_CONFIG,
        )

    assert "exceeds" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_file_write_allows_non_empty_content() -> None:
    tool = create_file_write_tool()
    mock_executor = MagicMock()

    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_write_tool.ensure_executor",
            return_value=mock_executor,
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_write_tool.FileOperationService",
        ) as mock_service_cls,
    ):
        mock_service_cls.return_value.execute = AsyncMock(
            return_value="Successfully created reports/week.md"
        )
        result = await tool.ainvoke(
            {"path": "reports/week.md", "content": "# Weekly report\n"},
            config=_DUMMY_CONFIG,
        )

    assert "Successfully created" in str(result)
    mock_service_cls.return_value.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_file_write_tool_permission_denied() -> None:
    tool = create_file_write_tool()

    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_write_tool.ensure_executor",
            return_value=MagicMock(),
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_write_tool.FileOperationService",
        ) as mock_service_cls,
        pytest.raises(ToolError) as exc_info,
    ):
        mock_service_cls.return_value.execute = AsyncMock(
            side_effect=PermissionError("denied")
        )
        await tool.ainvoke(
            {"path": "x.py", "content": "print(1)"},
            config=_DUMMY_CONFIG,
        )

    assert "Permission denied" in str(exc_info.value.user_hint)


@pytest.mark.asyncio
async def test_file_write_tool_value_error() -> None:
    tool = create_file_write_tool()

    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_write_tool.ensure_executor",
            return_value=MagicMock(),
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_write_tool.FileOperationService",
        ) as mock_service_cls,
        pytest.raises(ToolError) as exc_info,
    ):
        mock_service_cls.return_value.execute = AsyncMock(
            side_effect=ValueError("bad path")
        )
        await tool.ainvoke(
            {"path": "x.py", "content": "print(1)"},
            config=_DUMMY_CONFIG,
        )

    assert "Invalid parameter" in str(exc_info.value.user_hint)


@pytest.mark.asyncio
async def test_file_write_tool_unexpected_error() -> None:
    tool = create_file_write_tool()

    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_write_tool.ensure_executor",
            return_value=MagicMock(),
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_write_tool.FileOperationService",
        ) as mock_service_cls,
        pytest.raises(ToolError) as exc_info,
    ):
        mock_service_cls.return_value.execute = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        await tool.ainvoke(
            {"path": "x.py", "content": "print(1)"},
            config=_DUMMY_CONFIG,
        )

    assert "unexpected error occurred" in str(exc_info.value.user_hint).lower()
