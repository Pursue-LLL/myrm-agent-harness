"""Unit tests for file_edit_tool factory and error mapping."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool import (
    FileEditInput,
    create_file_edit_tool,
)
from myrm_agent_harness.utils.errors import ToolError

_DUMMY_CONFIG = RunnableConfig()


@pytest.mark.asyncio
async def test_file_edit_tool_success() -> None:
    tool = create_file_edit_tool()
    mock_executor = MagicMock()

    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool.require_executor",
            return_value=mock_executor,
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool.FileOperationService",
        ) as mock_service_cls,
    ):
        mock_service_cls.return_value.execute = AsyncMock(
            return_value="Successfully replaced text in a.py"
        )
        result = await tool.ainvoke(
            {
                "path": "a.py",
                "edits": [{"old_str": "old", "new_str": "new"}],
            },
            config=_DUMMY_CONFIG,
        )

    assert "Successfully replaced" in str(result)


@pytest.mark.asyncio
async def test_file_edit_tool_file_not_found() -> None:
    tool = create_file_edit_tool()

    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool.require_executor",
            return_value=MagicMock(),
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool.FileOperationService",
        ) as mock_service_cls,
    ):
        mock_service_cls.return_value.execute = AsyncMock(
            side_effect=FileNotFoundError("missing")
        )
        with pytest.raises(ToolError) as exc_info:
            await tool.ainvoke(
                {"path": "x.py", "edits": [{"old_str": "a", "new_str": "b"}]},
                config=_DUMMY_CONFIG,
            )
        assert "does not exist" in str(exc_info.value.user_hint)


@pytest.mark.asyncio
async def test_file_edit_tool_permission_denied() -> None:
    tool = create_file_edit_tool()

    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool.require_executor",
            return_value=MagicMock(),
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool.FileOperationService",
        ) as mock_service_cls,
    ):
        mock_service_cls.return_value.execute = AsyncMock(
            side_effect=PermissionError("denied")
        )
        with pytest.raises(ToolError) as exc_info:
            await tool.ainvoke(
                {"path": "x.py", "edits": [{"old_str": "a", "new_str": "b"}]},
                config=_DUMMY_CONFIG,
            )
        assert "Permission denied" in str(exc_info.value.user_hint)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_message", "hint_fragment"),
    [
        ("text not found in file", "not found"),
        ("old_str appears 3 times", "multiple times"),
        ("Edits 1 and 2 overlap", "overlap"),
        ("invalid parameter", "Invalid edit parameters"),
    ],
)
async def test_file_edit_tool_value_error_hints(
    error_message: str, hint_fragment: str
) -> None:
    tool = create_file_edit_tool()

    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool.require_executor",
            return_value=MagicMock(),
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool.FileOperationService",
        ) as mock_service_cls,
    ):
        mock_service_cls.return_value.execute = AsyncMock(
            side_effect=ValueError(error_message)
        )
        with pytest.raises(ToolError) as exc_info:
            await tool.ainvoke(
                {"path": "x.py", "edits": [{"old_str": "a", "new_str": "b"}]},
                config=_DUMMY_CONFIG,
            )
        assert hint_fragment.lower() in str(exc_info.value.user_hint).lower()


@pytest.mark.asyncio
async def test_file_edit_tool_unexpected_error() -> None:
    tool = create_file_edit_tool()

    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool.require_executor",
            return_value=MagicMock(),
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool.FileOperationService",
        ) as mock_service_cls,
    ):
        mock_service_cls.return_value.execute = AsyncMock(
            side_effect=RuntimeError("boom")
        )
        with pytest.raises(ToolError, match="Unexpected error"):
            await tool.ainvoke(
                {"path": "x.py", "edits": [{"old_str": "a", "new_str": "b"}]},
                config=_DUMMY_CONFIG,
            )


@pytest.mark.asyncio
async def test_file_edit_tool_passthrough_tool_error() -> None:
    tool = create_file_edit_tool()
    original = ToolError(message="gate", user_hint="read first")

    with (
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool.require_executor",
            return_value=MagicMock(),
        ),
        patch(
            "myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool.FileOperationService",
        ) as mock_service_cls,
    ):
        mock_service_cls.return_value.execute = AsyncMock(side_effect=original)
        with pytest.raises(ToolError) as exc_info:
            await tool.ainvoke(
                {"path": "x.py", "edits": [{"old_str": "a", "new_str": "b"}]},
                config=_DUMMY_CONFIG,
            )
        assert exc_info.value is original


def test_file_edit_input_legacy_flat_fields() -> None:
    model = FileEditInput.model_validate(
        {"path": "f.py", "old_string": "1", "new_string": "2"}
    )
    assert model.edits[0].old_str == "1"
    assert model.edits[0].new_str == "2"


def test_file_edit_input_non_dict_passthrough() -> None:
    assert FileEditInput.normalize_llm_payload("raw") == "raw"
