"""Static guards for web_search_tool description (query-rewrite SSOT)."""

from __future__ import annotations

import tiktoken

from myrm_agent_harness.toolkits.web_search._web_search_tool_description import (
    WEB_SEARCH_TOOL_DESCRIPTION,
)

_ENCODING = tiktoken.get_encoding("cl100k_base")

# Quality-first Chinese baseline; fail CI if the description regrows without review.
_MAX_DESCRIPTION_TOKENS = 2000


def test_web_search_tool_description_token_budget() -> None:
    tokens = len(_ENCODING.encode(WEB_SEARCH_TOOL_DESCRIPTION))
    assert tokens <= _MAX_DESCRIPTION_TOKENS, (
        f"web_search_tool description is {tokens} tokens "
        f"(maximum {_MAX_DESCRIPTION_TOKENS}); "
        "review quality-first prompt changes explicitly"
    )


def test_web_search_tool_description_preserves_rewrite_guardrails() -> None:
    desc = WEB_SEARCH_TOOL_DESCRIPTION
    required_fragments = (
        "每条 query 脱离会话和其他 query 后都必须可理解",
        "单独出现且没有上下文的缩写、代号或短名称",
        "禁止同义改写",
        "复杂问题可额外加入一条综合 query",
        "time_range：仅当用户明确给出时间范围或相对时间要求时设置",
        "用户要求官方或权威来源时，在 query 中使用 site:",
        "若结果没有覆盖回答所需的关键方面，优先改写缺失方面或增加互补 query",
    )
    forbidden_fragments = (
        "依赖搜索提供商",
        "并非所有提供商",
        "Provider-dependent",
    )
    for fragment in required_fragments:
        assert fragment in desc, f"missing rewrite guardrail fragment: {fragment!r}"
    for fragment in forbidden_fragments:
        assert fragment not in desc, f"implementation detail leaked into prompt: {fragment!r}"


def test_web_search_tool_description_is_chinese_quality_first_version() -> None:
    desc = WEB_SEARCH_TOOL_DESCRIPTION
    assert "web_search_tool 用于检索" in desc
    assert "Query 改写规则" in desc
    # Original English opening must not remain as the primary description.
    assert "Use this tool when the user's question" not in desc
