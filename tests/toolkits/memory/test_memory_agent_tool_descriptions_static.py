"""Static guards for memory agent tool descriptions (prompt SSOT)."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory._memory_agent_tool_descriptions import (
    DEFAULT_MEMORY_TOOL_DESCRIPTION_LOCALE,
    MEMORY_MANAGE_TOOL_DESCRIPTION,
    MEMORY_MANAGE_TOOL_DESCRIPTION_EN,
    MEMORY_MANAGE_TOOL_DESCRIPTION_ZH,
    MEMORY_SAVE_TOOL_DESCRIPTION,
    MEMORY_SAVE_TOOL_DESCRIPTION_EN,
    MEMORY_SAVE_TOOL_DESCRIPTION_ZH,
    build_memory_search_tool_description,
    resolve_memory_manage_tool_description,
    resolve_memory_save_tool_description,
)
from myrm_agent_harness.toolkits.memory.memory_search_policy import MemorySearchPolicy
from myrm_agent_harness.utils.text_utils import PLANNING_ENCODING, get_token_count

_MAX_SAVE_DESCRIPTION_TOKENS = 900
_MAX_MANAGE_DESCRIPTION_TOKENS = 400
_MAX_SEARCH_DESCRIPTION_TOKENS = 300


def test_default_locale_is_english() -> None:
    assert DEFAULT_MEMORY_TOOL_DESCRIPTION_LOCALE == "en"
    assert MEMORY_SAVE_TOOL_DESCRIPTION is MEMORY_SAVE_TOOL_DESCRIPTION_EN
    assert MEMORY_MANAGE_TOOL_DESCRIPTION is MEMORY_MANAGE_TOOL_DESCRIPTION_EN
    assert resolve_memory_save_tool_description() == MEMORY_SAVE_TOOL_DESCRIPTION_EN
    assert resolve_memory_manage_tool_description() == MEMORY_MANAGE_TOOL_DESCRIPTION_EN


def test_memory_save_tool_description_token_budget() -> None:
    for desc in (MEMORY_SAVE_TOOL_DESCRIPTION_EN, MEMORY_SAVE_TOOL_DESCRIPTION_ZH):
        tokens = get_token_count(desc, encoding_name=PLANNING_ENCODING)
        assert (
            tokens <= _MAX_SAVE_DESCRIPTION_TOKENS
        ), f"memory_save_tool description is {tokens} tokens (max {_MAX_SAVE_DESCRIPTION_TOKENS})"


def test_memory_manage_tool_description_token_budget() -> None:
    for desc in (MEMORY_MANAGE_TOOL_DESCRIPTION_EN, MEMORY_MANAGE_TOOL_DESCRIPTION_ZH):
        tokens = get_token_count(desc, encoding_name=PLANNING_ENCODING)
        assert (
            tokens <= _MAX_MANAGE_DESCRIPTION_TOKENS
        ), f"memory_manage_tool description is {tokens} tokens (max {_MAX_MANAGE_DESCRIPTION_TOKENS})"


def test_memory_search_tool_description_token_budget() -> None:
    policy = MemorySearchPolicy()
    for locale in ("en", "zh"):
        desc = build_memory_search_tool_description(policy, locale=locale)
        tokens = get_token_count(desc, encoding_name=PLANNING_ENCODING)
        assert tokens <= _MAX_SEARCH_DESCRIPTION_TOKENS, (
            f"memory_search_tool ({locale}) description is {tokens} tokens "
            f"(max {_MAX_SEARCH_DESCRIPTION_TOKENS})"
        )


def test_memory_tool_descriptions_preserve_guardrails_en() -> None:
    save = MEMORY_SAVE_TOOL_DESCRIPTION_EN
    manage = MEMORY_MANAGE_TOOL_DESCRIPTION_EN
    search = build_memory_search_tool_description(MemorySearchPolicy(), locale="en")
    assert "**WHEN TO SAVE**" in save
    assert "**WHAT NOT TO SAVE**" in save
    assert "corpus=sessions" in save
    assert "**WHEN TO USE**" in manage
    assert "memory_search results" in manage
    assert "**Corpus guide**" in search
    assert "profile_key" in search


def test_memory_tool_descriptions_preserve_guardrails_zh() -> None:
    save = MEMORY_SAVE_TOOL_DESCRIPTION_ZH
    manage = MEMORY_MANAGE_TOOL_DESCRIPTION_ZH
    search = build_memory_search_tool_description(MemorySearchPolicy(), locale="zh")
    assert "**何时保存**" in save
    assert "**不要保存**" in save
    assert "corpus=sessions" in save
    assert "**何时使用**" in manage
    assert "memory_search" in manage
    assert "**Corpus 指南**" in search
    assert "profile_key" in search


def test_create_memory_tools_uses_description_ssot(
    memory_config, mock_vector_store, mock_embedding
) -> None:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager
    from myrm_agent_harness.toolkits.memory.memory_agent_tools import (
        create_memory_tools,
    )

    manager = MemoryManager(
        memory_config,
        user_id="test-user",
        vector=mock_vector_store,
        embedding=mock_embedding,
    )
    tools = create_memory_tools(manager)
    by_name = {tool.name: tool for tool in tools}
    assert by_name["memory_save_tool"].description == MEMORY_SAVE_TOOL_DESCRIPTION_EN
    assert (
        by_name["memory_manage_tool"].description == MEMORY_MANAGE_TOOL_DESCRIPTION_EN
    )
    assert by_name[
        "memory_search_tool"
    ].description == build_memory_search_tool_description(
        MemorySearchPolicy(), locale="en"
    )


def test_memory_search_description_omits_disabled_corpora() -> None:
    policy = MemorySearchPolicy(allow_wiki=False, allow_sessions=False, allow_web=False)
    desc = build_memory_search_tool_description(policy, locale="en")
    assert "- wiki:" not in desc
    assert "- sessions:" not in desc
    assert "- web:" not in desc
    assert "- memory (default)" in desc
    assert "- all:" in desc

    policy_wiki = MemorySearchPolicy(allow_wiki=True, allow_sessions=False)
    desc_wiki = build_memory_search_tool_description(policy_wiki, locale="en")
    assert "- wiki:" in desc_wiki
    assert "- sessions:" not in desc_wiki


def test_memory_search_description_includes_enabled_corpora() -> None:
    policy = MemorySearchPolicy(allow_wiki=True, allow_sessions=True, allow_web=True)
    desc = build_memory_search_tool_description(policy, locale="en")
    assert "- wiki:" in desc
    assert "- sessions:" in desc
    assert "- web:" in desc


def test_memory_tool_descriptions_support_zh_cn_locale() -> None:
    assert (
        resolve_memory_save_tool_description("zh-CN") == MEMORY_SAVE_TOOL_DESCRIPTION_ZH
    )
    assert (
        resolve_memory_manage_tool_description("zh-CN")
        == MEMORY_MANAGE_TOOL_DESCRIPTION_ZH
    )
    search = build_memory_search_tool_description(MemorySearchPolicy(), locale="zh-CN")
    assert "**Corpus 指南**" in search


def test_create_memory_tools_supports_chinese_locale(
    memory_config, mock_vector_store, mock_embedding
) -> None:
    from myrm_agent_harness.toolkits.memory.manager import MemoryManager
    from myrm_agent_harness.toolkits.memory.memory_agent_tools import (
        create_memory_tools,
    )

    manager = MemoryManager(
        memory_config,
        user_id="test-user",
        vector=mock_vector_store,
        embedding=mock_embedding,
    )
    tools = create_memory_tools(manager, description_locale="zh-CN")
    by_name = {tool.name: tool for tool in tools}
    assert by_name["memory_save_tool"].description == MEMORY_SAVE_TOOL_DESCRIPTION_ZH
    assert (
        by_name["memory_manage_tool"].description == MEMORY_MANAGE_TOOL_DESCRIPTION_ZH
    )
    assert by_name[
        "memory_search_tool"
    ].description == build_memory_search_tool_description(
        MemorySearchPolicy(), locale="zh"
    )
