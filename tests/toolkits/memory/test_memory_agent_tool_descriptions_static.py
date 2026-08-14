"""Static guards for memory agent tool descriptions (prompt SSOT)."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory._memory_agent_tool_descriptions import (
    DEFAULT_MEMORY_TOOL_DESCRIPTION_LOCALE,
    MEMORY_MANAGE_TOOL_DESCRIPTION,
    MEMORY_MANAGE_TOOL_DESCRIPTION_EN,
    MEMORY_MANAGE_TOOL_DESCRIPTION_ZH,
    MEMORY_SAVE_CORE_EN,
    MEMORY_SAVE_CORE_ZH,
    MEMORY_SAVE_TOOL_DESCRIPTION,
    MEMORY_SAVE_TOOL_DESCRIPTION_EN,
    build_memory_save_tool_description,
    build_memory_search_tool_description,
    resolve_memory_manage_tool_description,
    resolve_memory_save_tool_description,
)
from myrm_agent_harness.toolkits.memory.memory_search_policy import MemorySearchPolicy
from myrm_agent_harness.toolkits.memory.wiki_memory_boundary import (
    WIKI_MEMORY_SAVE_MAX_CHARS,
    WIKI_MEMORY_SAVE_MIN_HEADINGS,
)
from myrm_agent_harness.utils.text_utils import PLANNING_ENCODING, get_token_count

_MAX_SAVE_CORE_TOKENS = 750
_MAX_SAVE_FULL_TOKENS = 900
_MAX_MANAGE_DESCRIPTION_TOKENS = 400
_MAX_SEARCH_DESCRIPTION_TOKENS = 300


def test_default_locale_is_english() -> None:
    assert DEFAULT_MEMORY_TOOL_DESCRIPTION_LOCALE == "en"
    assert MEMORY_SAVE_TOOL_DESCRIPTION is MEMORY_SAVE_TOOL_DESCRIPTION_EN
    assert MEMORY_SAVE_TOOL_DESCRIPTION_EN is MEMORY_SAVE_CORE_EN
    assert MEMORY_MANAGE_TOOL_DESCRIPTION is MEMORY_MANAGE_TOOL_DESCRIPTION_EN
    assert resolve_memory_save_tool_description() == build_memory_save_tool_description(
        MemorySearchPolicy(), locale="en"
    )
    assert resolve_memory_manage_tool_description() == MEMORY_MANAGE_TOOL_DESCRIPTION_EN


def test_mcp_surface_maps_gui_tool_names() -> None:
    manage_mcp = resolve_memory_manage_tool_description(surface="mcp")
    assert "memory_recall" in manage_mcp
    assert "memory_store" in manage_mcp
    assert "memory_search_tool" not in manage_mcp
    assert "memory_save_tool" not in manage_mcp

    store_mcp = build_memory_save_tool_description(
        MemorySearchPolicy(allow_wiki=True),
        surface="mcp",
    )
    assert "memory_manage" in store_mcp
    assert "do not store via memory_store" in store_mcp
    assert "memory_save_tool" not in store_mcp
    assert "WIKI BOUNDARY" in store_mcp
    assert "wiki_ingest_tool" not in store_mcp


def test_mcp_surface_zh_never_leaks_gui_wiki_tool() -> None:
    """Chinese MCP surface must never reference the GUI-only wiki_ingest_tool.

    Covers both the default description and the explicit wiki-enabled safety
    net (the ZH replacement pair strips the GUI tool reference from the
    WIKI BOUNDARY fragment).
    """
    from myrm_agent_harness.toolkits.memory._memory_agent_tool_descriptions import (
        build_mcp_memory_store_tool_description,
    )

    default_zh = build_mcp_memory_store_tool_description(locale="zh")
    assert "wiki_ingest_tool" not in default_zh

    wiki_enabled_zh = build_mcp_memory_store_tool_description(
        wiki_boundary_in_description=True,
        locale="zh",
    )
    assert "wiki_ingest_tool" not in wiki_enabled_zh
    assert "Wiki 边界" in wiki_enabled_zh
    assert "长文/笔记/参考资料不属于 memory" in wiki_enabled_zh


def test_memory_save_core_description_token_budget() -> None:
    for desc in (MEMORY_SAVE_CORE_EN, MEMORY_SAVE_CORE_ZH):
        tokens = get_token_count(desc, encoding_name=PLANNING_ENCODING)
        assert tokens <= _MAX_SAVE_CORE_TOKENS, (
            f"memory_save_tool core description is {tokens} tokens (max {_MAX_SAVE_CORE_TOKENS})"
        )


def test_memory_save_full_description_token_budget_with_wiki_and_approval() -> None:
    policy = MemorySearchPolicy(allow_wiki=True)
    for locale in ("en", "zh"):
        desc = build_memory_save_tool_description(
            policy,
            approval_required=True,
            locale=locale,
        )
        tokens = get_token_count(desc, encoding_name=PLANNING_ENCODING)
        assert tokens <= _MAX_SAVE_FULL_TOKENS, (
            f"memory_save_tool full ({locale}) description is {tokens} tokens (max {_MAX_SAVE_FULL_TOKENS})"
        )


def test_memory_manage_tool_description_token_budget() -> None:
    for desc in (MEMORY_MANAGE_TOOL_DESCRIPTION_EN, MEMORY_MANAGE_TOOL_DESCRIPTION_ZH):
        tokens = get_token_count(desc, encoding_name=PLANNING_ENCODING)
        assert tokens <= _MAX_MANAGE_DESCRIPTION_TOKENS, (
            f"memory_manage_tool description is {tokens} tokens (max {_MAX_MANAGE_DESCRIPTION_TOKENS})"
        )


def test_memory_search_tool_description_token_budget() -> None:
    policy = MemorySearchPolicy()
    for locale in ("en", "zh"):
        desc = build_memory_search_tool_description(policy, locale=locale)
        tokens = get_token_count(desc, encoding_name=PLANNING_ENCODING)
        assert tokens <= _MAX_SEARCH_DESCRIPTION_TOKENS, (
            f"memory_search_tool ({locale}) description is {tokens} tokens (max {_MAX_SEARCH_DESCRIPTION_TOKENS})"
        )


def test_memory_tool_descriptions_preserve_guardrails_en() -> None:
    save = MEMORY_SAVE_CORE_EN
    manage = MEMORY_MANAGE_TOOL_DESCRIPTION_EN
    search = build_memory_search_tool_description(MemorySearchPolicy(), locale="en")
    assert "**WHEN TO SAVE**" in save
    assert "do this proactively" in save
    assert "memory_manage_tool" in save
    assert "corpus=sessions" in save
    assert "memory_search_tool" in save
    assert "do not set rule_trigger" in save
    assert "**CATEGORY GUIDE**" in save
    assert "instruction-style, gets misinterpreted as a command" in save
    assert "**ATTRIBUTION & TRANSIENT STATES**" in save
    assert "**WHEN TO USE**" in manage
    assert "memory_save_tool" in manage
    assert "memory_search_tool" in manage
    assert "correct → knowledge only" in manage
    assert "preserves history" in manage
    assert "instruction saves" in manage
    assert "category=rule" in manage
    assert "Parameter semantics are in the tool schema" in manage
    assert "**Corpus guide**" in search
    assert "profile_key" in search


def test_memory_tool_descriptions_preserve_guardrails_zh() -> None:
    save = MEMORY_SAVE_CORE_ZH
    manage = MEMORY_MANAGE_TOOL_DESCRIPTION_ZH
    search = build_memory_search_tool_description(MemorySearchPolicy(), locale="zh")
    assert "**何时保存**" in save
    assert "memory_manage_tool" in save
    assert "corpus=sessions" in save
    assert "memory_search_tool" in save
    assert "不要设置 rule_trigger" in save
    assert "**类别指南**" in save
    assert "指令式，易被误解为命令" in save
    assert "**归属与短暂状态**" in save
    assert "长期或慢性状况" in save
    assert "**何时使用**" in manage
    assert "memory_save_tool" in manage
    assert "correct → 仅 knowledge" in manage
    assert "保留历史记录" in manage
    assert "instruction 保存" in manage
    assert "category=rule" in manage
    assert "参数说明见工具参数定义" in manage
    assert "**Corpus 指南**" in search
    assert "profile_key" in search


def test_memory_save_description_omits_wiki_boundary_when_disabled() -> None:
    desc = build_memory_save_tool_description(MemorySearchPolicy(), locale="en")
    assert "wiki_ingest_tool" not in desc
    assert "WIKI BOUNDARY" not in desc


def test_memory_save_description_includes_wiki_boundary_when_enabled() -> None:
    desc = build_memory_save_tool_description(
        MemorySearchPolicy(allow_wiki=True),
        locale="en",
    )
    assert "wiki_ingest_tool" in desc
    assert str(WIKI_MEMORY_SAVE_MAX_CHARS) in desc
    assert str(WIKI_MEMORY_SAVE_MIN_HEADINGS) in desc


def test_memory_save_description_includes_approval_when_required() -> None:
    desc = build_memory_save_tool_description(
        MemorySearchPolicy(),
        approval_required=True,
        locale="en",
    )
    assert "submitted for approval" in desc


def test_create_memory_tools_uses_description_ssot(memory_config, mock_vector_store, mock_embedding) -> None:
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
    expected_save = build_memory_save_tool_description(
        MemorySearchPolicy(),
        approval_required=manager.approval_required,
        locale="en",
    )
    assert by_name["memory_save_tool"].description == expected_save
    assert by_name["memory_manage_tool"].description == MEMORY_MANAGE_TOOL_DESCRIPTION_EN
    assert by_name["memory_search_tool"].description == build_memory_search_tool_description(
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


def test_memory_search_description_zh_includes_all_enabled_corpora() -> None:
    policy = MemorySearchPolicy(allow_wiki=True, allow_sessions=True, allow_web=True)
    desc = build_memory_search_tool_description(policy, locale="zh-CN")
    assert "web corpus" in desc
    assert "- web：" in desc
    assert "corpus=web" in desc
    assert "Wiki 文档" in desc
    assert "历史会话" in desc


def test_memory_tool_descriptions_support_zh_cn_locale() -> None:
    assert resolve_memory_save_tool_description("zh-CN") == build_memory_save_tool_description(
        MemorySearchPolicy(), locale="zh-CN"
    )
    assert resolve_memory_manage_tool_description("zh-CN") == MEMORY_MANAGE_TOOL_DESCRIPTION_ZH
    search = build_memory_search_tool_description(MemorySearchPolicy(), locale="zh-CN")
    assert "**Corpus 指南**" in search


def test_create_memory_tools_supports_chinese_locale(memory_config, mock_vector_store, mock_embedding) -> None:
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
    expected_save = build_memory_save_tool_description(
        MemorySearchPolicy(),
        approval_required=manager.approval_required,
        locale="zh-CN",
    )
    assert by_name["memory_save_tool"].description == expected_save
    assert by_name["memory_manage_tool"].description == MEMORY_MANAGE_TOOL_DESCRIPTION_ZH
    assert by_name["memory_search_tool"].description == build_memory_search_tool_description(
        MemorySearchPolicy(), locale="zh"
    )
