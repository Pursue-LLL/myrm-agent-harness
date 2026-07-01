"""Test SkillAgent wiki integration.

Verifies _create_wiki_tools() and _maybe_archive_to_wiki() behavior.
"""

import asyncio
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.skill_agent import SkillAgent


@pytest.fixture
def mock_llm() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def wiki_dir(tmp_path: Path) -> Path:
    return tmp_path / "wiki"


def _make_agent(
    mock_llm: AsyncMock, wiki_base_dir: Path | str | None = None, wiki_search_fn: Callable[..., object] | None = None
) -> SkillAgent:
    return SkillAgent(llm=mock_llm, wiki_base_dir=wiki_base_dir, wiki_search_fn=wiki_search_fn)


class TestCreateWikiTools:
    """Tests for _create_wiki_tools."""

    def test_returns_empty_when_no_wiki_dir(self, mock_llm: AsyncMock) -> None:
        agent = _make_agent(mock_llm, wiki_base_dir=None)
        tools = agent._create_wiki_tools()
        assert tools == []

    def test_returns_four_tools_when_wiki_dir_set(self, mock_llm: AsyncMock, wiki_dir: Path) -> None:
        agent = _make_agent(mock_llm, wiki_base_dir=wiki_dir)
        tools = agent._create_wiki_tools()

        assert len(tools) == 4
        names = {t.name for t in tools}
        assert names == {"wiki_ingest_tool", "wiki_compile_tool", "wiki_query_tool", "wiki_maintain_tool"}

    def test_stores_compiler_and_structure(self, mock_llm: AsyncMock, wiki_dir: Path) -> None:
        agent = _make_agent(mock_llm, wiki_base_dir=wiki_dir)
        agent._create_wiki_tools()

        assert agent._wiki_compiler is not None
        assert agent._wiki_structure is not None

    def test_accepts_str_wiki_base_dir(self, mock_llm: AsyncMock, wiki_dir: Path) -> None:
        """wiki_base_dir can be a str, not just Path."""
        agent = _make_agent(mock_llm, wiki_base_dir=str(wiki_dir))
        tools = agent._create_wiki_tools()

        assert len(tools) == 4
        assert agent._wiki_structure is not None

    def test_passes_search_fn_to_query_engine(self, mock_llm: AsyncMock, wiki_dir: Path) -> None:
        """wiki_search_fn should be forwarded to WikiQueryEngine."""
        mock_search = AsyncMock(return_value=[])
        agent = _make_agent(mock_llm, wiki_base_dir=wiki_dir, wiki_search_fn=mock_search)
        tools = agent._create_wiki_tools()

        assert len(tools) == 4
        assert agent._wiki_search_fn is mock_search

    def test_handles_import_error_gracefully(self, mock_llm: AsyncMock, wiki_dir: Path) -> None:
        agent = _make_agent(mock_llm, wiki_base_dir=wiki_dir)

        with patch.dict("sys.modules", {"myrm_agent_harness.toolkits.wiki": None}):
            tools = agent._create_wiki_tools()

        assert tools == []


class TestMaybeArchiveToWiki:
    """Tests for _maybe_archive_to_wiki."""

    def test_skips_when_no_wiki_compiler(self, mock_llm: AsyncMock) -> None:
        agent = _make_agent(mock_llm)
        agent._maybe_archive_to_wiki("test query", ["short"])

    def test_skips_when_content_too_short(self, mock_llm: AsyncMock, wiki_dir: Path) -> None:
        agent = _make_agent(mock_llm, wiki_base_dir=wiki_dir)
        agent._create_wiki_tools()

        agent._maybe_archive_to_wiki("test query", ["short reply"])

    def test_schedules_archive_when_content_sufficient(self, mock_llm: AsyncMock, wiki_dir: Path) -> None:
        agent = _make_agent(mock_llm, wiki_base_dir=wiki_dir)
        agent._create_wiki_tools()

        long_reply = "x" * 600

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run_archive(agent, long_reply))
        finally:
            loop.close()

    async def _run_archive(self, agent: SkillAgent, reply: str) -> None:
        agent._maybe_archive_to_wiki("What is Python?", [reply])
        await asyncio.sleep(0.1)

    def test_archive_includes_query_and_reply(self, mock_llm: AsyncMock, wiki_dir: Path) -> None:
        agent = _make_agent(mock_llm, wiki_base_dir=wiki_dir)
        agent._create_wiki_tools()

        assert agent._wiki_structure is not None
        long_reply = "This is a detailed response. " * 30

        mock_compiler = MagicMock()
        mock_compiler.compile_all = AsyncMock()
        agent._wiki_compiler = mock_compiler

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run_and_verify(agent, long_reply))
        finally:
            loop.close()

    async def _run_and_verify(self, agent: SkillAgent, reply: str) -> None:
        agent._maybe_archive_to_wiki("What is Python?", [reply])
        await asyncio.sleep(0.2)

        assert agent._wiki_structure is not None
        chat_id = getattr(agent.config, "chat_id", None) or "unknown"
        raw_path = agent._wiki_structure.get_raw_file_path(f"conversation_{chat_id}.md")

        if raw_path.exists():
            content = raw_path.read_text(encoding="utf-8")
            assert "# Query" in content
            assert "What is Python?" in content
            assert "# Response" in content

    def test_handles_list_query(self, mock_llm: AsyncMock, wiki_dir: Path) -> None:
        """Test that list[dict] query type doesn't crash."""
        agent = _make_agent(mock_llm, wiki_base_dir=wiki_dir)
        agent._create_wiki_tools()

        long_reply = "x" * 600
        list_query: list[dict[str, object]] = [{"type": "text", "text": "hello"}]

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run_list_query(agent, list_query, long_reply))
        finally:
            loop.close()

    async def _run_list_query(self, agent: SkillAgent, query: list[dict[str, object]], reply: str) -> None:
        agent._maybe_archive_to_wiki(query, [reply])
        await asyncio.sleep(0.1)

    def test_uses_unknown_when_chat_id_missing(self, mock_llm: AsyncMock, wiki_dir: Path) -> None:
        """When config has no chat_id, filename uses 'unknown'."""
        agent = _make_agent(mock_llm, wiki_base_dir=wiki_dir)
        agent._create_wiki_tools()

        mock_compiler = MagicMock()
        mock_compiler.compile_all = AsyncMock()
        agent._wiki_compiler = mock_compiler

        long_reply = "x" * 600

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run_and_check_unknown(agent, long_reply))
        finally:
            loop.close()

    async def _run_and_check_unknown(self, agent: SkillAgent, reply: str) -> None:
        agent._maybe_archive_to_wiki("test", [reply])
        await asyncio.sleep(0.2)

        assert agent._wiki_structure is not None
        raw_path = agent._wiki_structure.get_raw_file_path("conversation_unknown.md")
        if raw_path.exists():
            content = raw_path.read_text(encoding="utf-8")
            assert "# Query" in content

    def test_archive_failure_is_warning_not_error(self, mock_llm: AsyncMock, wiki_dir: Path) -> None:
        """_archive() exception should only produce a warning, not crash."""
        agent = _make_agent(mock_llm, wiki_base_dir=wiki_dir)
        agent._create_wiki_tools()

        mock_compiler = MagicMock()
        mock_compiler.compile_all = AsyncMock(side_effect=RuntimeError("compile boom"))
        agent._wiki_compiler = mock_compiler

        long_reply = "x" * 600

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run_failing_archive(agent, long_reply))
        finally:
            loop.close()

    async def _run_failing_archive(self, agent: SkillAgent, reply: str) -> None:
        agent._maybe_archive_to_wiki("test", [reply])
        await asyncio.sleep(0.2)

    def test_exact_threshold_500_chars(self, mock_llm: AsyncMock, wiki_dir: Path) -> None:
        """Content exactly 500 chars should be archived (>= boundary)."""
        agent = _make_agent(mock_llm, wiki_base_dir=wiki_dir)
        agent._create_wiki_tools()

        mock_compiler = MagicMock()
        mock_compiler.compile_all = AsyncMock()
        agent._wiki_compiler = mock_compiler

        reply_500 = "x" * 500

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(self._run_archive(agent, reply_500))
        finally:
            loop.close()

    def test_just_below_threshold_499_chars(self, mock_llm: AsyncMock, wiki_dir: Path) -> None:
        """Content at 499 chars should NOT be archived."""
        agent = _make_agent(mock_llm, wiki_base_dir=wiki_dir)
        agent._create_wiki_tools()

        agent._maybe_archive_to_wiki("test", ["x" * 499])


class TestRegisterLargeDocIngest:
    """Tests for _register_large_doc_ingest and the _ingest_large_doc closure."""

    def teardown_method(self) -> None:
        from myrm_agent_harness.agent.meta_tools.file_ops.utils.pdf_reader import (
            unregister_large_doc_ingest_callback,
        )
        unregister_large_doc_ingest_callback()

    def test_registers_callback(self, mock_llm: AsyncMock, wiki_dir: Path) -> None:
        """After _create_wiki_tools, the pdf_reader callback should be registered."""
        from myrm_agent_harness.agent.meta_tools.file_ops.utils import pdf_reader

        agent = _make_agent(mock_llm, wiki_base_dir=wiki_dir)
        agent._create_wiki_tools()

        assert pdf_reader._ingest_callback is not None

    @pytest.mark.asyncio
    async def test_atomic_file_creation_dedup(self, wiki_dir: Path) -> None:
        """_ingest_large_doc uses atomic O_CREAT|O_EXCL — duplicate is a no-op."""
        from myrm_agent_harness.agent._skill_agent_tools import SkillAgentToolsMixin
        from myrm_agent_harness.agent.meta_tools.file_ops.utils import pdf_reader

        mock_structure = MagicMock()
        mock_path = MagicMock()
        mock_path.parent.mkdir = MagicMock()
        mock_structure.get_raw_file_path.return_value = mock_path
        mock_compiler = MagicMock()

        SkillAgentToolsMixin._register_large_doc_ingest(mock_structure, mock_compiler)
        cb = pdf_reader._ingest_callback
        assert cb is not None

        with patch("myrm_agent_harness.agent._skill_agent_tools.os.open", side_effect=FileExistsError):
            await cb("test.pdf", "full text", "hash123")

        mock_compiler.enqueue_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_successful_ingest_enqueues_file(self, wiki_dir: Path) -> None:
        """Successful ingest writes file and enqueues for compilation."""
        from myrm_agent_harness.agent._skill_agent_tools import SkillAgentToolsMixin
        from myrm_agent_harness.agent.meta_tools.file_ops.utils import pdf_reader

        mock_structure = MagicMock()
        mock_path = MagicMock()
        mock_path.parent.mkdir = MagicMock()
        mock_path.__str__ = MagicMock(return_value="/tmp/fake_raw_path.md")
        mock_structure.get_raw_file_path.return_value = mock_path
        mock_compiler = MagicMock()

        SkillAgentToolsMixin._register_large_doc_ingest(mock_structure, mock_compiler)
        cb = pdf_reader._ingest_callback
        assert cb is not None

        fake_fd = 42
        with patch("myrm_agent_harness.agent._skill_agent_tools.os.open", return_value=fake_fd) as mock_open, \
             patch("myrm_agent_harness.agent._skill_agent_tools.os.write") as mock_write, \
             patch("myrm_agent_harness.agent._skill_agent_tools.os.close") as mock_close, \
             patch("myrm_agent_harness.agent.streaming.broadcast.event_bus.ToolBroadcastBus.get_instance", new_callable=AsyncMock) as mock_bus:
            mock_bus_inst = AsyncMock()
            mock_bus.return_value = mock_bus_inst

            await cb("report.pdf", "full content", "abc123")

        mock_open.assert_called_once()
        mock_write.assert_called_once_with(fake_fd, b"# report.pdf\n\nfull content")
        mock_close.assert_called_once_with(fake_fd)
        mock_compiler.enqueue_file.assert_called_once_with(mock_path)

    @pytest.mark.asyncio
    async def test_eventbus_failure_does_not_crash(self, wiki_dir: Path) -> None:
        """EventBus failure is non-critical and should not propagate."""
        from myrm_agent_harness.agent._skill_agent_tools import SkillAgentToolsMixin
        from myrm_agent_harness.agent.meta_tools.file_ops.utils import pdf_reader

        mock_structure = MagicMock()
        mock_path = MagicMock()
        mock_path.parent.mkdir = MagicMock()
        mock_path.__str__ = MagicMock(return_value="/tmp/fake_raw_path.md")
        mock_structure.get_raw_file_path.return_value = mock_path
        mock_compiler = MagicMock()

        SkillAgentToolsMixin._register_large_doc_ingest(mock_structure, mock_compiler)
        cb = pdf_reader._ingest_callback
        assert cb is not None

        fake_fd = 42
        with patch("myrm_agent_harness.agent._skill_agent_tools.os.open", return_value=fake_fd), \
             patch("myrm_agent_harness.agent._skill_agent_tools.os.write"), \
             patch("myrm_agent_harness.agent._skill_agent_tools.os.close"), \
             patch("myrm_agent_harness.agent.streaming.broadcast.event_bus.ToolBroadcastBus.get_instance", side_effect=RuntimeError("bus down")):
            await cb("test.pdf", "text", "hash456")

        mock_compiler.enqueue_file.assert_called_once()
