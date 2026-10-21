"""Web search meta-tool blocked-term decontamination tests."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.errors import ToolErrorCategory
from myrm_agent_harness.toolkits.web_search.providers.web_searcher import SearchServiceConfig
from myrm_agent_harness.toolkits.web_search.web_search_agent_tools import (
    create_web_search_tool,
)
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
    from unittest.mock import patch

    import myrm_agent_harness.toolkits.web_search.engine as engine_mod

    with patch.object(engine_mod.WebSearchTools, "fast_search_with_questions") as mock_search:
        mock_search.return_value = ([], "")
        result = await tool.ainvoke({"questions": ["best chess openings"], "reason": "probe"})
        assert "content" in result
        assert "metadata" in result
        mock_search.assert_awaited_once()


@pytest.mark.asyncio
async def test_case_insensitive_block() -> None:
    tool = _make_tool(("HUGGINGFACE",))
    with pytest.raises(ToolError):
        await tool.ainvoke({"questions": ["huggingface dataset download"], "reason": ""})


@pytest.mark.asyncio
async def test_block_error_text() -> None:
    tool = _make_tool(("hf.co",))
    try:
        await tool.ainvoke({"questions": ["search hf.co rows"], "reason": ""})
    except ToolError as exc:
        assert "Search query blocked" in str(exc)
        assert exc.error_category == ToolErrorCategory.BENCHMARK_BLOCKED.value
    else:  # pragma: no cover
        pytest.fail("expected ToolError")


@pytest.mark.asyncio
async def test_blocked_hostname_results_dropped_before_format() -> None:
    """Results whose URL host matches blocked_hostnames never reach formatting."""
    from unittest.mock import AsyncMock, patch

    from langchain_core.documents import Document

    from myrm_agent_harness.toolkits.web_search.engine import WebSearchTools

    cfg = SearchServiceConfig(search_service="perplexity", api_key="test-key")
    tools = WebSearchTools(config=cfg)

    mock_results = [
        (
            "query1",
            [
                Document(
                    page_content="hf content",
                    metadata={"url": "https://huggingface.co/models/leak"},
                ),
                Document(
                    page_content="alias content",
                    metadata={"url": "https://hf.co/datasets/x"},
                ),
                Document(
                    page_content="clean content",
                    metadata={"url": "https://example.com/article"},
                ),
            ],
            None,
        )
    ]

    with patch.object(
        tools._searcher,
        "multi_query_parallel_search",
        new_callable=AsyncMock,
        return_value=mock_results,
    ):
        sources, formatted = await tools.fast_search_with_questions(
            questions=["test query"],
            blocked_hostnames=("huggingface.co", "*.huggingface.co", "hf.co", "*.hf.co"),
        )

    assert len(sources) == 1
    assert sources[0]["url"] == "https://example.com/article"
    assert "huggingface" not in formatted.lower()
    assert "hf.co" not in formatted.lower()


@pytest.mark.asyncio
async def test_blocked_hostnames_none_passthrough() -> None:
    """Without blocked_hostnames every result is retained."""
    from unittest.mock import AsyncMock, patch

    from langchain_core.documents import Document

    from myrm_agent_harness.toolkits.web_search.engine import WebSearchTools

    cfg = SearchServiceConfig(search_service="perplexity", api_key="test-key")
    tools = WebSearchTools(config=cfg)

    mock_results = [
        (
            "query1",
            [
                Document(
                    page_content="hf content",
                    metadata={"url": "https://huggingface.co/models/leak"},
                ),
                Document(
                    page_content="clean content",
                    metadata={"url": "https://example.com/article"},
                ),
            ],
            None,
        )
    ]

    with patch.object(
        tools._searcher,
        "multi_query_parallel_search",
        new_callable=AsyncMock,
        return_value=mock_results,
    ):
        sources, formatted = await tools.fast_search_with_questions(questions=["test query"])

    assert len(sources) == 2
    assert "huggingface" in formatted.lower()


@pytest.mark.asyncio
async def test_tool_forwards_blocked_hostnames_to_engine() -> None:
    """create_web_search_tool passes blocked_hostnames into the engine call."""
    from unittest.mock import AsyncMock, patch

    from myrm_agent_harness.toolkits.web_search import engine as engine_mod

    tool = create_web_search_tool(
        SearchServiceConfig(search_service="perplexity", api_key="test-key"),
        blocked_hostnames=("huggingface.co",),
    )

    with patch.object(engine_mod.WebSearchTools, "fast_search_with_questions", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = ([], "")
        await tool.ainvoke({"questions": ["best chess openings"], "reason": "probe"})

    mock_search.assert_awaited_once()
    assert mock_search.await_args.kwargs.get("blocked_hostnames") == ("huggingface.co",)
