"""Tests for code_search agent tool factory.

Covers:
- Tool creation and metadata
- CodeSearchInput schema validation
- Search output formatting (file paths, scores, symbols, truncation)
- No-results fallback message
- Stats footer in output
"""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from myrm_agent_harness.toolkits.code_index.config import CodeIndexConfig
from myrm_agent_harness.toolkits.code_index.indexer import CodeIndexer


class TestCodeSearchInput:
    """Input schema validation."""

    def test_valid_input(self) -> None:
        from myrm_agent_harness.agent.meta_tools.code_search.tool import CodeSearchInput
        inp = CodeSearchInput(query="auth handler", scope="src/", limit=5)
        assert inp.query == "auth handler"
        assert inp.scope == "src/"
        assert inp.limit == 5

    def test_defaults(self) -> None:
        from myrm_agent_harness.agent.meta_tools.code_search.tool import CodeSearchInput
        inp = CodeSearchInput(query="test")
        assert inp.scope == ""
        assert inp.limit == 10

    def test_limit_bounds(self) -> None:
        from myrm_agent_harness.agent.meta_tools.code_search.tool import CodeSearchInput
        with pytest.raises(ValidationError):
            CodeSearchInput(query="test", limit=0)
        with pytest.raises(ValidationError):
            CodeSearchInput(query="test", limit=51)

    def test_extra_fields_forbidden(self) -> None:
        from myrm_agent_harness.agent.meta_tools.code_search.tool import CodeSearchInput
        with pytest.raises(ValidationError):
            CodeSearchInput(query="test", unknown_field="value")


class TestCreateCodeSearchTool:
    """Tool factory and output behavior."""

    @pytest.fixture()
    def workspace(self, tmp_path: Path) -> Path:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "handler.py").write_text(textwrap.dedent("""\
            class RequestHandler:
                def handle(self, request):
                    return "ok"

            def process_auth(token: str) -> bool:
                return True
        """))
        return tmp_path

    @pytest.fixture()
    def indexer(self, workspace: Path) -> CodeIndexer:
        config = CodeIndexConfig(enable_vector_search=False)
        return CodeIndexer(workspace, config)

    def test_tool_has_correct_name(self, indexer: CodeIndexer) -> None:
        from myrm_agent_harness.agent.meta_tools.code_search.tool import create_code_search_tool
        t = create_code_search_tool(indexer)
        assert t.name == "code_search_tool"

    def test_tool_has_description(self, indexer: CodeIndexer) -> None:
        from myrm_agent_harness.agent.meta_tools.code_search.tool import create_code_search_tool
        t = create_code_search_tool(indexer)
        assert "search" in t.description.lower()
        assert len(t.description) > 20

    def test_tool_returns_results(self, indexer: CodeIndexer) -> None:
        from myrm_agent_harness.agent.meta_tools.code_search.tool import create_code_search_tool
        t = create_code_search_tool(indexer)
        mock_config = MagicMock()
        mock_config.get.return_value = None

        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            t.ainvoke({"query": "RequestHandler", "scope": "", "limit": 10}, config=mock_config)
        )
        assert "handler.py" in result
        assert "Found" in result

    def test_tool_no_results(self, indexer: CodeIndexer) -> None:
        from myrm_agent_harness.agent.meta_tools.code_search.tool import create_code_search_tool
        t = create_code_search_tool(indexer)
        mock_config = MagicMock()
        mock_config.get.return_value = None

        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            t.ainvoke({"query": "zzz_nonexistent_thing", "scope": "", "limit": 10}, config=mock_config)
        )
        assert "No code matches found" in result

    def test_tool_includes_stats_footer(self, indexer: CodeIndexer) -> None:
        from myrm_agent_harness.agent.meta_tools.code_search.tool import create_code_search_tool
        t = create_code_search_tool(indexer)
        mock_config = MagicMock()
        mock_config.get.return_value = None

        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            t.ainvoke({"query": "handle", "scope": "", "limit": 10}, config=mock_config)
        )
        if "Found" in result:
            assert "[Index:" in result

    def test_tool_scope_filter(self, indexer: CodeIndexer, workspace: Path) -> None:
        (workspace / "other").mkdir()
        (workspace / "other" / "misc.py").write_text("def other_func():\n    pass\n")

        from myrm_agent_harness.agent.meta_tools.code_search.tool import create_code_search_tool
        t = create_code_search_tool(indexer)
        mock_config = MagicMock()
        mock_config.get.return_value = None

        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(
            t.ainvoke({"query": "func", "scope": "src/", "limit": 10}, config=mock_config)
        )
        if "Found" in result:
            assert "other/" not in result
