"""Static guards for web_search_tool description (query-rewrite SSOT)."""

from __future__ import annotations

from myrm_agent_harness.toolkits.web_search._web_search_tool_description import (
    DEFAULT_WEB_SEARCH_TOOL_DESCRIPTION_LOCALE,
    WEB_SEARCH_TOOL_DESCRIPTION,
    WEB_SEARCH_TOOL_DESCRIPTION_EN,
    WEB_SEARCH_TOOL_DESCRIPTION_ZH,
    resolve_web_search_tool_description,
)
from myrm_agent_harness.toolkits.web_search.engine import SearchServiceConfig
from myrm_agent_harness.toolkits.web_search.web_search_agent_tools import (
    create_web_search_tool,
)
from myrm_agent_harness.utils.text_utils import PLANNING_ENCODING, get_token_count

_MAX_DESCRIPTION_TOKENS = 2000


def test_default_locale_is_english() -> None:
    assert DEFAULT_WEB_SEARCH_TOOL_DESCRIPTION_LOCALE == "en"
    assert WEB_SEARCH_TOOL_DESCRIPTION is WEB_SEARCH_TOOL_DESCRIPTION_EN
    assert resolve_web_search_tool_description() == WEB_SEARCH_TOOL_DESCRIPTION_EN


def test_web_search_tool_description_token_budget() -> None:
    for desc in (WEB_SEARCH_TOOL_DESCRIPTION_EN, WEB_SEARCH_TOOL_DESCRIPTION_ZH):
        tokens = get_token_count(desc, encoding_name=PLANNING_ENCODING)
        assert tokens <= _MAX_DESCRIPTION_TOKENS, (
            f"web_search_tool description is {tokens} tokens "
            f"(maximum {_MAX_DESCRIPTION_TOKENS}); "
            "review quality-first prompt changes explicitly"
        )


def test_web_search_tool_description_preserves_rewrite_guardrails_en() -> None:
    desc = WEB_SEARCH_TOOL_DESCRIPTION_EN
    required_fragments = (
        "Each query must be understandable on its own, outside the conversation and other queries",
        "abbreviations, codes, or short names that appear alone without context",
        "Do not produce synonymous rewrites",
        "a complex question may additionally include one synthesis query",
        "time_range: Set only when the user explicitly gives a time range",
        "use site: in the query to restrict domains",
        "If results do not cover key aspects needed to answer, prefer rewriting for missing aspects or adding complementary queries",
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


def test_web_search_tool_description_preserves_rewrite_guardrails_zh() -> None:
    desc = WEB_SEARCH_TOOL_DESCRIPTION_ZH
    required_fragments = (
        "每条 query 脱离会话和其他 query 后都必须可理解",
        "补全单独出现且没有上下文的缩写、代号或短名称",
        "禁止同义改写或信息重叠",
        "复杂问题可额外加入一条综合 query",
        "time_range：仅当用户明确给出时间范围",
        "site:",
        "若结果没有覆盖回答所需的关键方面，优先改写缺失方面或增加互补 query",
    )
    forbidden_fragments = (
        "Provider-dependent",
        "依赖搜索提供商",
    )
    for fragment in required_fragments:
        assert fragment in desc, f"missing rewrite guardrail fragment: {fragment!r}"
    for fragment in forbidden_fragments:
        assert fragment not in desc, f"implementation detail leaked into prompt: {fragment!r}"


def test_create_web_search_tool_default_english_description() -> None:
    tool = create_web_search_tool(
        search_service_cfg=SearchServiceConfig(search_service="tavily", api_key="test-key"),
    )
    assert tool.description == WEB_SEARCH_TOOL_DESCRIPTION_EN


def test_create_web_search_tool_chinese_locale() -> None:
    tool = create_web_search_tool(
        search_service_cfg=SearchServiceConfig(search_service="tavily", api_key="test-key"),
        description_locale="zh-CN",
    )
    assert tool.description == WEB_SEARCH_TOOL_DESCRIPTION_ZH
    assert tool.description.startswith("web_search_tool 用于检索")
