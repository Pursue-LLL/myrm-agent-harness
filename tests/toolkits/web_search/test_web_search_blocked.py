"""Web search meta-tool blocked-term decontamination tests."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.web_search.web_search_agent_tools import (
    create_web_search_tool,
)
from myrm_agent_harness.toolkits.web_search.web_searcher import SearchServiceConfig
from myrm_agent_harness.utils.errors import ToolError


def _make_tool(blocked_terms: tuple[str, ...]) -> object:
    cfg = SearchServiceConfig(search_service="perplexity", api_key="test-key")
    return create_web_search_tool(cfg, blocked_terms=blocked_terms)


@pytest.mark.asyncio
async def test_blocked_query_rejected_before_search() -> None:
    tool = _make_tool(("huggingface", "hf.co"))
    with pytest.raises(ToolError) as exc_info:
        await tool.ainvoke(
            {
                "questions": ["find the huggingface model card"],
                "reason": "decontamination probe",
            }
        )
    assert exc_info.value.error_code == "BENCHMARK_BLOCKED_QUERY"


@pytest.mark.asyncio
async def test_clean_queries_pass_through() -> None:
    """Blocklist must not touch unrelated queries (tool still rejects by config)."""
    tool = _make_tool(("huggingface",))
    # The blocklist check runs before the real search, so reaching the search
    # layer means the query is allowed. We patch the engine to avoid network.
    import myrm_agent_harness.toolkits.web_search.engine as engine_mod
    from unittest.mock import patch

    with patch.object(
        engine_mod.WebSearchTools, "fast_search_with_questions"
    ) as mock_search:
        mock_search.return_value = ([], "")
        result = await tool.ainvoke(
            {"questions": ["best chess openings"], "reason": "probe"}
        )
        assert "content" in result
        assert "metadata" in result
        mock_search.assert_awaited_once()


@pytest.mark.asyncio
async def test_case_insensitive_block() -> None:
    tool = _make_tool(("HUGGINGFACE",))
    with pytest.raises(ToolError):
        await tool.ainvoke(
            {"questions": ["huggingface dataset download"], "reason": ""}
        )


@pytest.mark.asyncio
async def test_block_error_text() -> None:
    tool = _make_tool(("hf.co",))
    try:
        await tool.ainvoke(
            {"questions": ["search hf.co rows"], "reason": ""}
        )
    except ToolError as exc:
        assert "Search query blocked" in str(exc)
        assert exc.error_category == "benchmark_blocked"
    else:  # pragma: no cover
        pytest.fail("expected ToolError")
