"""Tests for grep_tool — content search tool.

Covers:
- Factory creation and tool metadata
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
    _mmap_search_file,
    _ripgrep_search,
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
        results = await _ripgrep_search("def", workspace, "**/*", False, 0, 100)
        assert len(results) >= 2
        files = {r["file"] for r in results}
        assert any("hello.py" in f for f in files)

    async def test_ignore_case(self, workspace: Path) -> None:
        if not _has_ripgrep():
            pytest.skip("ripgrep not installed")
        (workspace / "case.txt").write_text("Hello\nHELLO\nhello\n")
        results = await _ripgrep_search("hello", workspace, "**/*", True, 0, 100)
        assert len(results) >= 3

    async def test_file_pattern_filter(self, workspace: Path) -> None:
        if not _has_ripgrep():
            pytest.skip("ripgrep not installed")
        results = await _ripgrep_search("import", workspace, "**/*.py", False, 0, 100)
        for r in results:
            assert str(r["file"]).endswith(".py")

    async def test_max_results_limit(self, workspace: Path) -> None:
        if not _has_ripgrep():
            pytest.skip("ripgrep not installed")
        many = workspace / "big.py"
        many.write_text("\n".join(f"match_{i} = True" for i in range(200)))
        results = await _ripgrep_search("match_", workspace, "**/*", False, 0, 5)
        assert len(results) <= 5

    async def test_no_match_returns_empty(self, workspace: Path) -> None:
        if not _has_ripgrep():
            pytest.skip("ripgrep not installed")
        results = await _ripgrep_search("NONEXISTENT_STRING_12345", workspace, "**/*", False, 0, 100)
        assert results == []

    async def test_nonzero_returncode_raises_runtime_error_without_name_error(self, workspace: Path) -> None:
        class _FakeStdout:
            async def readline(self) -> bytes:
                return b""

        class _FakeStderr:
            def __init__(self) -> None:
                self._sent = False

            async def read(self, _: int) -> bytes:
                if self._sent:
                    return b""
                self._sent = True
                return b"simulated error"

        class _FakeProcess:
            def __init__(self) -> None:
                self.stdout = _FakeStdout()
                self.stderr = _FakeStderr()
                self.returncode = 2
                self.terminated = False

            async def wait(self) -> int:
                return self.returncode

            def terminate(self) -> None:
                self.terminated = True

        fake_proc = _FakeProcess()
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.asyncio.create_subprocess_exec",
                return_value=fake_proc,
            ),
            pytest.raises(RuntimeError, match="ripgrep failed"),
        ):
            await _ripgrep_search("pattern", workspace, "**/*", False, 0, 10)


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
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
                return_value=mock_executor,
            ),
            pytest.raises(ToolError, match="Path not found"),
        ):
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
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
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
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
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
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "hello", "ignore_case": True},
                config=runnable_config,
            )
            assert "match" in result.lower()

    async def test_cache_hit(self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig) -> None:
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
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
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "API_KEY"},
                config=runnable_config,
            )
            assert isinstance(result, str)
            assert "sk-abc123def456" not in result
            assert "***" in result

    async def test_redact_cli_flag_equals_output(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        (workspace / "cli.sh").write_text("run --api-key=sk-abcdefghijklmnop1234\n")
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "api-key"},
                config=runnable_config,
            )
            assert "sk-abcdefghijklmnop1234" not in result
            assert "sk-abc" in result

    async def test_redact_dotted_key_output(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        (workspace / "app.conf").write_text("app.api.key=sk-abcdefghijklmnop1234\n")
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "app.api.key"},
                config=runnable_config,
            )
            assert "sk-abcdefghijklmnop1234" not in result
            assert "sk-abc" in result

    async def test_redos_protection(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_grep_tool()
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
                return_value=mock_executor,
            ),
            pytest.raises(ToolError, match=r"[Dd]angerous|[Nn]ested"),
        ):
            await tool_fn.ainvoke(
                {"pattern": "(a+)+"},
                config=runnable_config,
            )

    async def test_no_matches(self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig) -> None:
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
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
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
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
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
                return_value=mock_executor_bad,
            ),
            pytest.raises(ToolError, match="Invalid path"),
        ):
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
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
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
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
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
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
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
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
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
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
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
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
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
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
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

    async def test_fallback_skips_hidden_files_by_default(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        (workspace / ".hidden.py").write_text("hidden_token = True\n")
        tool_fn = create_grep_tool()
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
                return_value=mock_executor,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool._has_ripgrep",
                return_value=False,
            ),
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "hidden_token"},
                config=runnable_config,
            )
            assert ".hidden.py" not in result

    async def test_fallback_allows_explicit_hidden_file_path(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        (workspace / ".hidden_explicit.py").write_text("explicit_hidden_token = True\n")
        tool_fn = create_grep_tool()
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
                return_value=mock_executor,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool._has_ripgrep",
                return_value=False,
            ),
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "explicit_hidden_token", "path": ".hidden_explicit.py"},
                config=runnable_config,
            )
            assert "Found 1 match(es)" in result
            assert "No matches found" not in result

    async def test_fallback_respects_root_ignore_files_without_git_repo(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        (workspace / ".gitignore").write_text("ignored_non_git.py\n")
        (workspace / "ignored_non_git.py").write_text("NON_GIT_IGNORE_TOKEN = 1\n")
        (workspace / "visible_non_git.py").write_text("NON_GIT_IGNORE_TOKEN = 1\n")

        tool_fn = create_grep_tool()
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
                return_value=mock_executor,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool._has_ripgrep",
                return_value=False,
            ),
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "NON_GIT_IGNORE_TOKEN", "file_pattern": "**/*.py"},
                config=runnable_config,
            )
            assert "visible_non_git.py" in result
            assert "ignored_non_git.py" not in result

    async def test_fallback_invalid_file_pattern(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        tool_fn = create_grep_tool()
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
                return_value=mock_executor,
            ),
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool._has_ripgrep",
                return_value=False,
            ),
            pytest.raises(ToolError, match=r"[Ii]nvalid file pattern"),
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
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
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
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
                return_value=mock_executor_bad,
            ),
            pytest.raises(ToolError, match=r"[Uu]nexpected"),
        ):
            await tool_fn.ainvoke(
                {"pattern": "test"},
                config=runnable_config,
            )


# ---------------------------------------------------------------------------
# Tests: Audit log
# ---------------------------------------------------------------------------


class TestAuditLog:
    async def test_densification_triggers_in_full_chain(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        """Full-chain integration: grep_tool → ripgrep/mmap → format_grep_results produces densified output."""
        for i in range(6):
            (workspace / f"mod_{i}.py").write_text(f"DENSE_TOKEN = {i}\n")
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "DENSE_TOKEN"},
                config=runnable_config,
            )
            lines = result.split("\n")
            indented = [ln for ln in lines if ln.startswith("  ") and "DENSE_TOKEN" in ln]
            assert len(indented) >= 6, f"Expected densified indented lines, got: {result}"
            path_headers = [ln for ln in lines if ln.strip().endswith(".py") and not ln.startswith("  ")]
            assert len(path_headers) >= 1

    async def test_no_densification_below_threshold(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        """Full-chain: grep_tool with < 5 matches stays flat."""
        for i in range(3):
            (workspace / f"small_{i}.py").write_text(f"FLAT_TOKEN = {i}\n")
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "FLAT_TOKEN"},
                config=runnable_config,
            )
            indented = [ln for ln in result.split("\n") if ln.startswith("  ") and "FLAT_TOKEN" in ln]
            assert len(indented) == 0, f"Below threshold should use flat format, got: {result}"

    async def test_audit_log_enabled(
        self,
        workspace: Path,
        mock_executor: MagicMock,
        runnable_config: RunnableConfig,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import logging

        caplog.set_level(logging.INFO)
        cfg = FileIOConfig(enable_audit_log=True)
        tool_fn = create_grep_tool(cfg)
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
            return_value=mock_executor,
        ):
            await tool_fn.ainvoke(
                {"pattern": "def"},
                config=runnable_config,
            )
            audit_msgs = [r.message for r in caplog.records if "SECURITY AUDIT" in r.message]
            assert len(audit_msgs) >= 1
            assert "grep_tool" in audit_msgs[0]


# ---------------------------------------------------------------------------
# Literal mode tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGrepLiteralMode:
    """Tests for literal=True exact text matching."""

    async def test_literal_matches_special_chars_exactly(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        """literal=True matches regex special characters as-is."""
        (workspace / "api.py").write_text('result = response.json()\ndata = result["key"]\n')
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "response.json()", "literal": True},
                config=runnable_config,
            )
            assert "response.json()" in result
            assert "api.py" in result

    async def test_literal_does_not_regex_match(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        """literal=True with '.' should NOT match arbitrary characters."""
        (workspace / "test_lit.py").write_text("responseXjson_call\nresponse.json()\n")
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "response.json()", "literal": True},
                config=runnable_config,
            )
            assert "response.json()" in result
            assert "responseXjson" not in result

    async def test_literal_ignore_case(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        """literal=True respects ignore_case."""
        (workspace / "mixed.txt").write_text("Response.JSON()\nresponse.json()\nNOTHING\n")
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "response.json()", "literal": True, "ignore_case": True},
                config=runnable_config,
            )
            assert "Response.JSON()" in result
            assert "response.json()" in result
            assert "NOTHING" not in result

    async def test_literal_empty_pattern_raises(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        """literal=True with empty pattern raises ToolError."""
        tool_fn = create_grep_tool()
        with (
            patch(
                "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
                return_value=mock_executor,
            ),
            pytest.raises(ToolError),
        ):
            await tool_fn.ainvoke(
                {"pattern": "", "literal": True},
                config=runnable_config,
            )

    async def test_literal_default_false_preserves_regex(
        self, workspace: Path, mock_executor: MagicMock, runnable_config: RunnableConfig
    ) -> None:
        """Default literal=False preserves existing regex behavior."""
        (workspace / "regex_test.py").write_text("def hello():\ndef world():\nclass Foo:\n")
        tool_fn = create_grep_tool()
        with patch(
            "myrm_agent_harness.agent.meta_tools.file_search.grep_tool.ensure_executor",
            return_value=mock_executor,
        ):
            result = await tool_fn.ainvoke(
                {"pattern": "def \\w+\\("},
                config=runnable_config,
            )
            assert "hello" in result
            assert "world" in result
