"""Architecture guard: harness tool invoke rules stay in tool schema."""

from __future__ import annotations

from pathlib import Path

import pytest

_HARNESS_SRC = Path(__file__).resolve().parents[2] / "src" / "myrm_agent_harness"


def test_model_discipline_does_not_import_web_search_query_policy() -> None:
    discipline_path = _HARNESS_SRC / "agent" / "streaming" / "model_discipline.py"
    source = discipline_path.read_text(encoding="utf-8")
    assert "search_query_policy" not in source
    assert "WEB_SEARCH_QUERY_GUIDANCE" not in source


def test_web_search_query_policy_module_removed() -> None:
    policy_path = _HARNESS_SRC / "toolkits" / "web_search" / "search_query_policy.py"
    assert not policy_path.is_file()


@pytest.mark.asyncio
async def test_web_search_tool_description_token_budget() -> None:
    import tiktoken

    from myrm_agent_harness.toolkits.web_search.engine import SearchServiceConfig
    from myrm_agent_harness.toolkits.web_search.web_search_agent_tools import (
        create_web_search_tool,
    )

    tool = create_web_search_tool(
        search_service_cfg=SearchServiceConfig(
            search_service="tavily", api_key="test-key"
        ),
    )
    encoding = tiktoken.get_encoding("cl100k_base")
    tokens = len(encoding.encode(tool.description or ""))
    assert (
        tokens <= 1300
    ), f"web_search_tool description bloated beyond baseline to {tokens} tok"
    assert (
        tokens >= 1000
    ), f"web_search_tool description trimmed below mid-tier baseline: {tokens} tok"
