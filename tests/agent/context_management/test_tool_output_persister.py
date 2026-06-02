"""Unit tests for tool_output_persister."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from myrm_agent_harness.agent.context_management.infra.tool_output_persister import (
    _sanitize_name,
    persist_large_tool_output,
)

_MOCK_WS = "myrm_agent_harness.agent.middlewares._session_context.get_workspace_root"


class TestSanitizeName:
    def test_normal_name(self) -> None:
        assert _sanitize_name("my_tool") == "my_tool"

    def test_special_characters(self) -> None:
        assert _sanitize_name("server/tool.name") == "server_tool_name"

    def test_spaces(self) -> None:
        assert _sanitize_name("my tool name") == "my_tool_name"

    def test_long_name_truncated(self) -> None:
        long_name = "a" * 100
        result = _sanitize_name(long_name)
        assert len(result) == 40

    def test_empty_name(self) -> None:
        assert _sanitize_name("") == "unknown"

    def test_all_special_chars_produce_underscores(self) -> None:
        result = _sanitize_name("@#$%^&*()")
        assert "_" in result
        assert len(result) > 0

    def test_hyphen_preserved(self) -> None:
        assert _sanitize_name("my-tool") == "my-tool"


class TestPersistLargeToolOutput:
    @pytest.mark.asyncio
    async def test_no_workspace_root_returns_none(self) -> None:
        with patch(_MOCK_WS, return_value=""):
            result = await persist_large_tool_output("content", "tool")
        assert result is None

    @pytest.mark.asyncio
    async def test_successful_persist(self, tmp_path: Path) -> None:
        content = "large output content " * 100
        workspace = str(tmp_path / "workspace")
        os.makedirs(workspace, exist_ok=True)

        with patch(_MOCK_WS, return_value=workspace):
            result = await persist_large_tool_output(content, "test_tool")

        assert result is not None
        assert result.startswith(".myrm/artifacts/tool_outputs/")
        assert "test_tool_" in result
        assert result.endswith(".txt")

        full_path = Path(workspace) / result
        assert full_path.exists()
        assert full_path.read_text(encoding="utf-8") == content

    @pytest.mark.asyncio
    async def test_creates_parent_directories(self, tmp_path: Path) -> None:
        workspace = str(tmp_path / "deep" / "nested" / "workspace")

        with patch(_MOCK_WS, return_value=workspace):
            result = await persist_large_tool_output("content", "tool")

        assert result is not None
        assert (Path(workspace) / result).exists()

    @pytest.mark.asyncio
    async def test_none_tool_name(self, tmp_path: Path) -> None:
        workspace = str(tmp_path)

        with patch(_MOCK_WS, return_value=workspace):
            result = await persist_large_tool_output("content", None)

        assert result is not None
        assert "tool_" in result

    @pytest.mark.asyncio
    async def test_special_chars_in_tool_name(self, tmp_path: Path) -> None:
        workspace = str(tmp_path)

        with patch(_MOCK_WS, return_value=workspace):
            result = await persist_large_tool_output("content", "mcp/server.query")

        assert result is not None
        assert "mcp_server_query_" in result
        assert (Path(workspace) / result).exists()

    @pytest.mark.asyncio
    async def test_write_failure_returns_none(self, tmp_path: Path) -> None:
        workspace = str(tmp_path)

        with (
            patch(_MOCK_WS, return_value=workspace),
            patch(
                "myrm_agent_harness.agent.context_management.infra.tool_output_persister.async_atomic_write",
                side_effect=OSError("disk full"),
            ),
        ):
            result = await persist_large_tool_output("content", "tool")

        assert result is None

    @pytest.mark.asyncio
    async def test_unicode_content(self, tmp_path: Path) -> None:
        workspace = str(tmp_path)
        content = "日本語テスト  中文内容 한국어"

        with patch(_MOCK_WS, return_value=workspace):
            result = await persist_large_tool_output(content, "tool")

        assert result is not None
        saved = (Path(workspace) / result).read_text(encoding="utf-8")
        assert saved == content

    @pytest.mark.asyncio
    async def test_relative_path_format(self, tmp_path: Path) -> None:
        """Returned path must be relative (no leading /)."""
        workspace = str(tmp_path)

        with patch(_MOCK_WS, return_value=workspace):
            result = await persist_large_tool_output("data", "my_tool")

        assert result is not None
        assert not result.startswith("/")
        assert result.startswith(".myrm/")


class TestFormatFilteredMessageWithSavedPath:
    def test_without_saved_path(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.filter import (
            FilteredResult,
            format_filtered_message,
        )

        result = FilteredResult(
            content_type="json",
            total_lines=100,
            total_chars=5000,
            estimated_tokens=2500,
            summary="JSON data",
            structure_overview="keys: [a, b, c]",
            read_suggestions=["re-execute tool"],
        )
        msg = format_filtered_message(result)
        assert "file_read_tool" not in msg
        assert "Full output saved to:" not in msg

    def test_with_saved_path(self) -> None:
        from myrm_agent_harness.agent.context_management.strategies.filter import (
            FilteredResult,
            format_filtered_message,
        )

        result = FilteredResult(
            content_type="json",
            total_lines=100,
            total_chars=5000,
            estimated_tokens=2500,
            summary="JSON data",
            structure_overview="keys: [a, b, c]",
            read_suggestions=["re-execute tool"],
        )
        msg = format_filtered_message(result, saved_path=".myrm/artifacts/tool_outputs/test.txt")
        assert "Full output saved to:" in msg
        assert ".myrm/artifacts/tool_outputs/test.txt" in msg
        assert "file_read_tool" in msg
