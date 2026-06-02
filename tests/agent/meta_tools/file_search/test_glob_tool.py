"""Tests for glob_tool — file name search tool.

Covers:
- Factory creation and tool metadata
- Basic glob matching (*, **, extensions)
- Path validation and error handling
- Result limit enforcement
- Empty result handling
- Sorted output
- Nested directory search
- Invalid pattern handling
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.config import FileIOConfig
from myrm_agent_harness.agent.meta_tools.file_search.glob_tool import (
    GlobInput,
    create_glob_tool,
)
from myrm_agent_harness.utils.errors import ToolError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace with test files."""
    (tmp_path / "main.py").write_text("print('main')\n")
    (tmp_path / "utils.py").write_text("def util(): pass\n")
    (tmp_path / "config.json").write_text("{}\n")
    (tmp_path / "README.md").write_text("# Hello\n")
    sub = tmp_path / "src"
    sub.mkdir()
    (sub / "app.py").write_text("app = True\n")
    (sub / "test_app.py").write_text("def test(): pass\n")
    deep = sub / "inner"
    deep.mkdir()
    (deep / "deep.py").write_text("x = 1\n")
    return tmp_path


@pytest.fixture
def mock_executor(workspace: Path) -> MagicMock:
    """Create a mock executor with resolve_path returning workspace paths."""
    executor = AsyncMock()

    async def _resolve_path(p: str) -> str:
        if p == ".":
            return str(workspace)
        return str(workspace / p)

    executor.resolve_path = _resolve_path
    return executor


@pytest.fixture
def runnable_config() -> RunnableConfig:
    return RunnableConfig(configurable={})


# ---------------------------------------------------------------------------
# Tests: GlobInput schema
# ---------------------------------------------------------------------------


class TestGlobInput:
    def test_defaults(self) -> None:
        inp = GlobInput(pattern="*.py")
        assert inp.path == "."

    def test_custom_values(self) -> None:
        inp = GlobInput(pattern="**/*.js", path="src")
        assert inp.pattern == "**/*.js"
        assert inp.path == "src"


# ---------------------------------------------------------------------------
# Tests: create_glob_tool
# ---------------------------------------------------------------------------


class TestCreateGlobTool:
    def test_factory_creates_tool(self) -> None:
        tool_fn = create_glob_tool()
        assert tool_fn.name == "glob_tool"
        assert "搜索匹配的文件" in tool_fn.description

    def test_custom_config(self) -> None:
        cfg = FileIOConfig(max_search_results=5)
        tool_fn = create_glob_tool(cfg)
        assert "5" in tool_fn.description

    async def test_find_python_files(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_glob_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.glob_tool.require_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke({"pattern": "*.py"}, config=runnable_config)
            assert "main.py" in result
            assert "utils.py" in result

    async def test_recursive_search(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_glob_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.glob_tool.require_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke({"pattern": "**/*.py"}, config=runnable_config)
            assert "deep.py" in result
            assert "app.py" in result

    async def test_test_file_pattern(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_glob_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.glob_tool.require_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke({"pattern": "**/test_*.py"}, config=runnable_config)
            assert "test_app.py" in result
            assert "main.py" not in result

    async def test_no_matches(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_glob_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.glob_tool.require_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke({"pattern": "*.xyz"}, config=runnable_config)
            assert "No files found" in result

    async def test_path_not_found(
        self, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_glob_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.glob_tool.require_executor",
            return_value=mock_executor,
        ), pytest.raises(ToolError, match="Path not found"):
            await tool_fn.ainvoke(
                {"pattern": "*.py", "path": "nonexistent"},
                config=runnable_config,
            )

    async def test_not_a_directory(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_glob_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.glob_tool.require_executor",
            return_value=mock_executor,
        ), pytest.raises(ToolError, match="Not a directory"):
            await tool_fn.ainvoke(
                {"pattern": "*.py", "path": "main.py"},
                config=runnable_config,
            )

    async def test_invalid_path_traversal(
        self, runnable_config: RunnableConfig
    ) -> None:
        mock_exec = AsyncMock()
        mock_exec.resolve_path = AsyncMock(side_effect=ValueError("path traversal"))
        tool_fn = create_glob_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.glob_tool.require_executor",
            return_value=mock_exec,
        ), pytest.raises(ToolError, match="Invalid path"):
            await tool_fn.ainvoke(
                {"pattern": "*.py", "path": "../../etc"},
                config=runnable_config,
            )

    async def test_result_limit(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        cfg = FileIOConfig(max_search_results=2)
        tool_fn = create_glob_tool(cfg)
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.glob_tool.require_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke({"pattern": "**/*.py"}, config=runnable_config)
            assert "限制显示前 2 个结果" in result

    async def test_output_sorted(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_glob_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.glob_tool.require_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke({"pattern": "*.py"}, config=runnable_config)
            lines = [l.strip() for l in result.strip().split("\n") if l.strip() and not l.startswith("Found")]
            assert lines == sorted(lines)

    async def test_search_subdirectory(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_glob_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.glob_tool.require_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke({"pattern": "*.py", "path": "src"}, config=runnable_config)
            assert "app.py" in result
            assert "main.py" not in result

    async def test_found_count_message(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_glob_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.glob_tool.require_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke({"pattern": "*.py"}, config=runnable_config)
            assert "Found" in result
            assert "file(s)" in result

    async def test_unexpected_error_becomes_tool_error(
        self, runnable_config: RunnableConfig
    ) -> None:
        mock_exec = AsyncMock()
        mock_exec.resolve_path = AsyncMock(side_effect=RuntimeError("unexpected boom"))
        tool_fn = create_glob_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.glob_tool.require_executor",
            return_value=mock_exec,
        ), pytest.raises(ToolError, match="[Uu]nexpected"):
            await tool_fn.ainvoke(
                {"pattern": "*.py"},
                config=runnable_config,
            )

    async def test_audit_log_enabled(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        caplog.set_level(logging.INFO)
        cfg = FileIOConfig(enable_audit_log=True)
        tool_fn = create_glob_tool(cfg)
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.glob_tool.require_executor",
            return_value=mock_executor,
        ):
            await tool_fn.ainvoke({"pattern": "*.py"}, config=runnable_config)
            audit_msgs = [r.message for r in caplog.records if "SECURITY AUDIT" in r.message]
            assert len(audit_msgs) >= 1
            assert "glob_tool" in audit_msgs[0]

    async def test_json_config_files(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_glob_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.glob_tool.require_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke({"pattern": "*.json"}, config=runnable_config)
            assert "config.json" in result
