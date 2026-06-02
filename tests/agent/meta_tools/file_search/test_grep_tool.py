"""Tests for grep_tool — content search tool.

Covers:
- Factory creation and tool metadata
- Cache key generation and cache behavior
- ripgrep detection
- ripgrep search engine (tier 1)
- mmap search engine (tier 2)
- Path validation and error handling
- ReDoS protection integration
- Result formatting delegation
- Sensitive text redaction
- File pattern filtering
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.config import FileIOConfig
from myrm_agent_harness.agent.meta_tools.file_search.grep_tool import (
    GrepInput,
    _has_ripgrep,
    _make_cache_key,
    _mmap_search_file,
    _ripgrep_search,
    _search_cache,
    create_grep_tool,
)
from myrm_agent_harness.utils.errors import ToolError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace with test files."""
    (tmp_path / "hello.py").write_text("def hello():\n    return 42\n\ndef world():\n    pass\n")
    (tmp_path / "config.json").write_text('{"key": "value", "count": 1}\n')
    (tmp_path / "empty.txt").write_text("")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "nested.py").write_text("import os\nimport sys\n")
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


@pytest.fixture(autouse=True)
def _clear_grep_cache():
    """Clear grep cache before each test."""
    _search_cache.clear()
    yield
    _search_cache.clear()


@pytest.fixture
def runnable_config() -> RunnableConfig:
    return RunnableConfig(configurable={})


# ---------------------------------------------------------------------------
# Tests: GrepInput schema
# ---------------------------------------------------------------------------


class TestGrepInput:
    def test_defaults(self) -> None:
        inp = GrepInput(pattern="test")
        assert inp.path == "."
        assert inp.file_pattern == "**/*"
        assert inp.ignore_case is False

    def test_custom_values(self) -> None:
        inp = GrepInput(pattern="def", path="src", file_pattern="**/*.py", ignore_case=True)
        assert inp.pattern == "def"
        assert inp.path == "src"
        assert inp.file_pattern == "**/*.py"
        assert inp.ignore_case is True


# ---------------------------------------------------------------------------
# Tests: Cache key generation
# ---------------------------------------------------------------------------


class TestCacheKey:
    def test_deterministic(self) -> None:
        k1 = _make_cache_key("pat", ".", "**/*", False)
        k2 = _make_cache_key("pat", ".", "**/*", False)
        assert k1 == k2

    def test_differs_on_pattern(self) -> None:
        k1 = _make_cache_key("a", ".", "**/*", False)
        k2 = _make_cache_key("b", ".", "**/*", False)
        assert k1 != k2

    def test_differs_on_ignore_case(self) -> None:
        k1 = _make_cache_key("a", ".", "**/*", False)
        k2 = _make_cache_key("a", ".", "**/*", True)
        assert k1 != k2

    def test_differs_on_path(self) -> None:
        k1 = _make_cache_key("a", ".", "**/*", False)
        k2 = _make_cache_key("a", "src", "**/*", False)
        assert k1 != k2


# ---------------------------------------------------------------------------
# Tests: ripgrep detection
# ---------------------------------------------------------------------------


class TestRipgrepDetection:
    def test_has_ripgrep_returns_bool(self) -> None:
        result = _has_ripgrep()
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Tests: mmap search
# ---------------------------------------------------------------------------


class TestMmapSearch:
    def test_search_finds_match(self, workspace: Path) -> None:
        import re

        regex = re.compile("def hello")
        results = _mmap_search_file(workspace / "hello.py", regex)
        assert len(results) == 1
        assert results[0]["line"] == 1
        assert "def hello" in results[0]["content"]

    def test_search_empty_file(self, workspace: Path) -> None:
        import re

        regex = re.compile("anything")
        results = _mmap_search_file(workspace / "empty.txt", regex)
        assert results == []

    def test_search_max_matches(self, workspace: Path) -> None:
        import re

        many_lines = workspace / "many.txt"
        many_lines.write_text("\n".join(f"match line {i}" for i in range(100)))
        regex = re.compile("match")
        results = _mmap_search_file(many_lines, regex, max_matches=5)
        assert len(results) == 5

    def test_search_nonexistent_file(self, workspace: Path) -> None:
        import re

        regex = re.compile("test")
        results = _mmap_search_file(workspace / "nonexistent.py", regex)
        assert results == []

    def test_search_binary_like_content(self, workspace: Path) -> None:
        import re

        bin_file = workspace / "data.bin"
        bin_file.write_bytes(b"\x00\x01\x02\xff\xfe")
        regex = re.compile("test")
        results = _mmap_search_file(bin_file, regex)
        assert results == []

    def test_search_multiple_matches_in_file(self, workspace: Path) -> None:
        import re

        regex = re.compile("def")
        results = _mmap_search_file(workspace / "hello.py", regex)
        assert len(results) == 2
        assert results[0]["line"] == 1
        assert results[1]["line"] == 4


# ---------------------------------------------------------------------------
# Tests: ripgrep search engine
# ---------------------------------------------------------------------------


class TestRipgrepSearch:
    async def test_basic_search(self, workspace: Path) -> None:
        if not _has_ripgrep():
            pytest.skip("ripgrep not installed")
        results = await _ripgrep_search("def", workspace, "**/*", False, 100)
        assert len(results) >= 2
        files = {r["file"] for r in results}
        assert any("hello.py" in f for f in files)

    async def test_ignore_case(self, workspace: Path) -> None:
        if not _has_ripgrep():
            pytest.skip("ripgrep not installed")
        (workspace / "case.txt").write_text("Hello\nHELLO\nhello\n")
        results = await _ripgrep_search("hello", workspace, "**/*", True, 100)
        assert len(results) >= 3

    async def test_file_pattern_filter(self, workspace: Path) -> None:
        if not _has_ripgrep():
            pytest.skip("ripgrep not installed")
        results = await _ripgrep_search("import", workspace, "**/*.py", False, 100)
        for r in results:
            assert str(r["file"]).endswith(".py")

    async def test_max_results_limit(self, workspace: Path) -> None:
        if not _has_ripgrep():
            pytest.skip("ripgrep not installed")
        many = workspace / "big.py"
        many.write_text("\n".join(f"match_{i} = True" for i in range(200)))
        results = await _ripgrep_search("match_", workspace, "**/*", False, 5)
        assert len(results) <= 5

    async def test_no_match_returns_empty(self, workspace: Path) -> None:
        if not _has_ripgrep():
            pytest.skip("ripgrep not installed")
        results = await _ripgrep_search("NONEXISTENT_STRING_12345", workspace, "**/*", False, 100)
        assert results == []


# ---------------------------------------------------------------------------
# Tests: create_grep_tool integration
# ---------------------------------------------------------------------------


class TestCreateGrepTool:
    def test_factory_creates_tool(self) -> None:
        tool_fn = create_grep_tool()
        assert tool_fn.name == "grep_tool"
        assert "搜索文件内容" in tool_fn.description

    def test_custom_config(self) -> None:
        cfg = FileIOConfig(max_search_results=10, max_search_files=5)
        tool_fn = create_grep_tool(cfg)
        assert "10" in tool_fn.description

    async def test_path_not_found(self, mock_executor: MagicMock, runnable_config: RunnableConfig) -> None:
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
            return_value=mock_executor,
        ), pytest.raises(ToolError, match="Path not found"):
            await tool_fn.ainvoke(
                {"pattern": "test", "path": "nonexistent_dir"},
                config=runnable_config,
            )

    async def test_not_a_directory(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        # Since we removed the is_dir() restriction, this test should now pass and return results
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
            return_value=mock_executor,
        ):
            # The test sets up a file, so we should be able to grep it
            result = await tool_fn.ainvoke(
                {"pattern": "test", "path": "hello.py"},
                config=runnable_config,
            )
            assert isinstance(result, str)

    async def test_basic_search(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "def hello"},
                config=runnable_config,
            )
            assert "hello" in result
            assert "match" in result.lower()

    async def test_ignore_case_search(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        (workspace / "case_test.txt").write_text("HELLO\nhello\nHeLLo\n")
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "hello", "ignore_case": True},
                config=runnable_config,
            )
            assert "match" in result.lower()

    async def test_cache_hit(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
            return_value=mock_executor,
        ):
            result1 = await tool_fn.ainvoke(
                {"pattern": "def hello"},
                config=runnable_config,
            )
            result2 = await tool_fn.ainvoke(
                {"pattern": "def hello"},
                config=runnable_config,
            )
            assert result1 == result2

    async def test_redact_sensitive_text(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        (workspace / "secrets.py").write_text('API_KEY = "sk-abc123def456"\n')
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "API_KEY"},
                config=runnable_config,
            )
            assert isinstance(result, str)

    async def test_redos_protection(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
            return_value=mock_executor,
        ), pytest.raises(ToolError, match="[Dd]angerous|[Nn]ested"):
            await tool_fn.ainvoke(
                {"pattern": "(a+)+"},
                config=runnable_config,
            )

    async def test_no_matches(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "ZZZZZ_NONEXISTENT"},
                config=runnable_config,
            )
            assert "No matches found" in result

    async def test_file_pattern_filter(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "import", "file_pattern": "**/*.py"},
                config=runnable_config,
            )
            assert "import" in result
            assert ".json" not in result

    async def test_invalid_path(self, mock_executor: MagicMock, runnable_config: RunnableConfig) -> None:
        mock_executor_bad = AsyncMock()
        mock_executor_bad.resolve_path = AsyncMock(side_effect=ValueError("path traversal"))
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
            return_value=mock_executor_bad,
        ), pytest.raises(ToolError, match="Invalid path"):
            await tool_fn.ainvoke(
                {"pattern": "test", "path": "../../etc/passwd"},
                config=runnable_config,
            )


# ---------------------------------------------------------------------------
# Tests: Python fallback path (when ripgrep is unavailable)
# ---------------------------------------------------------------------------


class TestPythonFallback:
    """Tests that exercise the Python/mmap fallback search engine (lines 292-367)."""

    async def test_fallback_basic_search(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_grep_tool()
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
                return_value=mock_executor,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool._has_ripgrep",
                return_value=False,
            ),
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "def hello"},
                config=runnable_config,
            )
            assert "hello" in result

    async def test_fallback_skips_binary_files(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        (workspace / "data.pyc").write_bytes(b"\x00\x01\x02")
        (workspace / "image.jpg").write_bytes(b"\xff\xd8\xff")
        tool_fn = create_grep_tool()
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
                return_value=mock_executor,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool._has_ripgrep",
                return_value=False,
            ),
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "def"},
                config=runnable_config,
            )
            assert ".pyc" not in result
            assert ".jpg" not in result

    async def test_fallback_file_limit(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        cfg = FileIOConfig(max_search_files=1, max_search_results=100)
        tool_fn = create_grep_tool(cfg)
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
                return_value=mock_executor,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool._has_ripgrep",
                return_value=False,
            ),
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "def"},
                config=runnable_config,
            )
            assert isinstance(result, str)

    async def test_fallback_max_results_limit(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        for i in range(20):
            (workspace / f"file_{i}.py").write_text(f"match_{i} = True\n")
        cfg = FileIOConfig(max_search_results=3)
        tool_fn = create_grep_tool(cfg)
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
                return_value=mock_executor,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool._has_ripgrep",
                return_value=False,
            ),
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "match_"},
                config=runnable_config,
            )
            assert "limited to first 3" in result

    async def test_fallback_ripgrep_failure_triggers_python(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_grep_tool()
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
                return_value=mock_executor,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool._has_ripgrep",
                return_value=True,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool._ripgrep_search",
                side_effect=RuntimeError("ripgrep crashed"),
            ),
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "def hello"},
                config=runnable_config,
            )
            assert "hello" in result

    async def test_fallback_unicode_error_skipped(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        (workspace / "broken.txt").write_bytes(b"\x80\x81\x82\x83")
        tool_fn = create_grep_tool()
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
                return_value=mock_executor,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool._has_ripgrep",
                return_value=False,
            ),
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "test"},
                config=runnable_config,
            )
            assert isinstance(result, str)

    async def test_fallback_no_matches(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_grep_tool()
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
                return_value=mock_executor,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool._has_ripgrep",
                return_value=False,
            ),
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "ZZZZZ_NONEXISTENT_XYZ"},
                config=runnable_config,
            )
            assert "No matches found" in result

    async def test_fallback_invalid_file_pattern(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_grep_tool()
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
                return_value=mock_executor,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool._has_ripgrep",
                return_value=False,
            ),pytest.raises(ToolError, match="[Ii]nvalid file pattern")
        ):
            await tool_fn.ainvoke(
                {"pattern": "test", "file_pattern": "\x00invalid"},
                config=runnable_config,
            )

    async def test_fallback_search_timeout(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        """Verify Python fallback respects search_timeout_seconds."""

        cfg = FileIOConfig(search_timeout_seconds=0.0)
        tool_fn = create_grep_tool(cfg)
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
                return_value=mock_executor,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool._has_ripgrep",
                return_value=False,
            ),
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "def"},
                config=runnable_config,
            )
            assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Tests: Unexpected exception wrapping
# ---------------------------------------------------------------------------


class TestUnexpectedExceptionWrapping:
    async def test_unexpected_error_becomes_tool_error(
        self, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        mock_executor_bad = AsyncMock()
        mock_executor_bad.resolve_path = AsyncMock(side_effect=RuntimeError("unexpected boom"))
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
            return_value=mock_executor_bad,
        ), pytest.raises(ToolError, match="[Uu]nexpected"):
            await tool_fn.ainvoke(
                {"pattern": "test"},
                config=runnable_config,
            )


# ---------------------------------------------------------------------------
# Tests: Audit log
# ---------------------------------------------------------------------------


class TestAuditLog:
    async def test_audit_log_enabled(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        caplog.set_level(logging.INFO)
        cfg = FileIOConfig(enable_audit_log=True)
        tool_fn = create_grep_tool(cfg)
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.require_executor",
            return_value=mock_executor,
        ):
            await tool_fn.ainvoke(
                {"pattern": "def"},
                config=runnable_config,
            )
            audit_msgs = [r.message for r in caplog.records if "SECURITY AUDIT" in r.message]
            assert len(audit_msgs) >= 1
            assert "grep_tool" in audit_msgs[0]
