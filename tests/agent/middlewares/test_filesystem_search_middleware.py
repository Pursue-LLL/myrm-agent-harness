"""Tests for FilesystemFileSearchMiddleware.

Verifies the LangChain AgentMiddleware contract, tool creation,
validation, and the double-registration prevention design.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from langchain.agents.middleware import AgentMiddleware

from myrm_agent_harness.agent.middlewares.filesystem_search_middleware import (
    FilesystemFileSearchMiddleware,
    create_filesystem_search_middleware,
)


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    (tmp_path / "hello.py").write_text("print('hi')")
    return tmp_path


class TestFilesystemFileSearchMiddleware:
    def test_inherits_agent_middleware(self, tmp_workspace: Path) -> None:
        mw = FilesystemFileSearchMiddleware(root_path=str(tmp_workspace))
        assert isinstance(mw, AgentMiddleware)

    def test_get_tools_returns_glob_and_grep(self, tmp_workspace: Path) -> None:
        mw = FilesystemFileSearchMiddleware(root_path=str(tmp_workspace))
        tools = mw.get_tools()
        assert len(tools) == 2
        names = {t.name for t in tools}
        assert "glob_tool" in names
        assert "grep_tool" in names

    def test_tools_not_exposed_publicly(self, tmp_workspace: Path) -> None:
        """LangChain collects via getattr(m, 'tools', []). We store in _tools
        to prevent double-registration with our own get_tools() path."""
        mw = FilesystemFileSearchMiddleware(root_path=str(tmp_workspace))
        assert getattr(mw, "tools", []) == []
        assert len(mw._tools) == 2

    def test_wrap_tool_call_satisfies_langchain_contract(self, tmp_workspace: Path) -> None:
        """LangChain factory calls hasattr(mw, 'wrap_tool_call') — must exist and be callable."""
        mw = FilesystemFileSearchMiddleware(root_path=str(tmp_workspace))
        assert hasattr(mw, "wrap_tool_call")
        assert callable(mw.wrap_tool_call)
        sentinel = object()
        assert mw.wrap_tool_call(sentinel, lambda r: r) is sentinel

    async def test_awrap_tool_call_is_async_and_awaits_handler(self, tmp_workspace: Path) -> None:
        """awrap_tool_call must be async def and correctly await the async handler."""
        mw = FilesystemFileSearchMiddleware(root_path=str(tmp_workspace))
        assert inspect.iscoroutinefunction(mw.awrap_tool_call)

        sentinel = object()

        async def async_handler(request: object) -> object:
            return request

        result = await mw.awrap_tool_call(sentinel, async_handler)
        assert result is sentinel

    def test_invalid_root_path_raises(self) -> None:
        with pytest.raises(ValueError, match="does not exist"):
            FilesystemFileSearchMiddleware(root_path="/nonexistent/path/xyz123")

    def test_root_path_must_be_directory(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("x")
        with pytest.raises(ValueError, match="not a directory"):
            FilesystemFileSearchMiddleware(root_path=str(f))

    def test_custom_config_propagated(self, tmp_workspace: Path) -> None:
        mw = FilesystemFileSearchMiddleware(
            root_path=str(tmp_workspace),
            max_file_size_mb=5,
            max_search_results=50,
            search_timeout_seconds=10.0,
        )
        assert mw.io_config.max_file_size_bytes == 5 * 1024 * 1024
        assert mw.io_config.max_search_results == 50
        assert mw.io_config.search_timeout_seconds == 10.0

    def test_tool_descriptions_contain_root_path(self, tmp_workspace: Path) -> None:
        mw = FilesystemFileSearchMiddleware(root_path=str(tmp_workspace))
        tools = mw.get_tools()
        for tool in tools:
            assert str(tmp_workspace) in tool.description


class TestCreateFilesystemSearchMiddleware:
    def test_factory_returns_middleware(self, tmp_workspace: Path) -> None:
        mw = create_filesystem_search_middleware(root_path=str(tmp_workspace))
        assert isinstance(mw, FilesystemFileSearchMiddleware)
        assert isinstance(mw, AgentMiddleware)

    def test_factory_passes_params(self, tmp_workspace: Path) -> None:
        mw = create_filesystem_search_middleware(
            root_path=str(tmp_workspace),
            max_search_results=25,
        )
        assert mw.io_config.max_search_results == 25
