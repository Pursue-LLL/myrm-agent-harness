"""Static guards for web_fetch_tool description (locale SSOT)."""

from __future__ import annotations

from myrm_agent_harness.toolkits.web_fetch._web_fetch_tool_description import (
    DEFAULT_WEB_FETCH_TOOL_DESCRIPTION_LOCALE,
    resolve_web_fetch_tool_description,
)
from myrm_agent_harness.toolkits.web_fetch.web_fetch_agent_tools import (
    create_web_fetch_tool,
)
from myrm_agent_harness.utils.text_utils import PLANNING_ENCODING, get_token_count

_MAX_DESCRIPTION_TOKENS = 2000


def test_default_locale_is_english() -> None:
    assert DEFAULT_WEB_FETCH_TOOL_DESCRIPTION_LOCALE == "en"
    assert resolve_web_fetch_tool_description(False) == (
        resolve_web_fetch_tool_description(False, None)
    )


def test_web_fetch_tool_description_token_budget() -> None:
    for enable_extract in (False, True):
        for locale in (None, "en", "zh-CN"):
            desc = resolve_web_fetch_tool_description(enable_extract, locale)
            tokens = get_token_count(desc, encoding_name=PLANNING_ENCODING)
            assert tokens <= _MAX_DESCRIPTION_TOKENS, (
                f"web_fetch_tool description is {tokens} tokens "
                f"(maximum {_MAX_DESCRIPTION_TOKENS}); "
                "review quality-first prompt changes explicitly"
            )


def test_web_fetch_tool_description_preserves_operation_guardrails_en() -> None:
    desc = resolve_web_fetch_tool_description(True, "en")
    required_fragments = (
        "fetch_and_extract",
        "Query rewriting rules",
        "handles JS rendering internally",
        "mp.weixin.qq.com",
        "For JS-heavy or interactive pages (clicking, filling forms, scrolling), use browser tools",
    )
    for fragment in required_fragments:
        assert fragment in desc, f"missing operation guardrail fragment: {fragment!r}"


def test_web_fetch_tool_description_preserves_operation_guardrails_zh() -> None:
    desc = resolve_web_fetch_tool_description(True, "zh-CN")
    required_fragments = (
        "fetch_and_extract",
        "query 改写规则",
        "内部处理 JS 渲染",
        "mp.weixin.qq.com",
        "点击、填表、滚动",
    )
    for fragment in required_fragments:
        assert fragment in desc, f"missing operation guardrail fragment: {fragment!r}"


def test_web_fetch_tool_description_never_leaks_policy_details() -> None:
    """Blocklist/decontamination internals must never reach the LLM prompt."""
    for enable_extract in (False, True):
        for locale in (None, "en", "zh-CN"):
            desc = resolve_web_fetch_tool_description(enable_extract, locale)
            for leaked in ("blocked", "decontam", "Hugging Face", "benchmark"):
                assert leaked not in desc, (
                    f"policy implementation detail leaked into prompt: {leaked!r}"
                )


def test_extract_mode_omitted_when_disabled() -> None:
    """Without extract capability the description must not mention it."""
    desc = resolve_web_fetch_tool_description(False, "en")
    assert "fetch_and_extract" not in desc
    assert "fetch_full_content" in desc


def test_create_web_fetch_tool_default_english_description() -> None:
    tool = create_web_fetch_tool()
    assert tool.description == resolve_web_fetch_tool_description(False, "en")


def test_create_web_fetch_tool_chinese_locale() -> None:
    tool = create_web_fetch_tool(description_locale="zh-CN")
    assert tool.description == resolve_web_fetch_tool_description(False, "zh-CN")
    assert tool.description.startswith("web_fetch_tool 从指定的网页 URL")
