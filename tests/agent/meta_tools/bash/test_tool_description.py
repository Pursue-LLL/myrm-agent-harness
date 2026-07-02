"""Static bash TOOL_DESCRIPTION prompt hygiene tests."""

from __future__ import annotations

import myrm_agent_harness.agent.skills.mcp.builtin_registry as registry_mod
from myrm_agent_harness.agent.meta_tools.bash._tool_description import TOOL_DESCRIPTION
from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import (
    create_bash_code_execute_tool,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_tool_helpers import get_os_hint
from myrm_agent_harness.agent.skills.mcp.builtin_registry import (
    get_builtin_tool_registry,
)


def test_ptc_section_uses_generic_rules_not_web_search() -> None:
    assert "函数名/参数与 Agent tool schema 一致" in TOOL_DESCRIPTION
    assert "单次调用仍用 native tool" in TOOL_DESCRIPTION
    assert "myrm_tools.web_search_tool" not in TOOL_DESCRIPTION
    assert "myrm_tools.file_read_tool" not in TOOL_DESCRIPTION
    assert "myrm_tools.session_store(key" in TOOL_DESCRIPTION


def test_tool_description_module_exports() -> None:
    from myrm_agent_harness.agent.meta_tools.bash import _tool_description as mod

    assert mod.__all__ == ["TOOL_DESCRIPTION"]
    assert len(TOOL_DESCRIPTION) > 500


def test_create_bash_tool_merges_static_os_hint_and_ptc_registry() -> None:
    registry_mod._registry = None
    registry = get_builtin_tool_registry()
    ptc_section = registry.get_ptc_description()

    bash_tool = create_bash_code_execute_tool()
    description = bash_tool.description

    assert description.startswith(TOOL_DESCRIPTION)
    assert get_os_hint() in description
    assert ptc_section in description
    assert "myrm_tools.web_search(" not in description
    assert "myrm_tools.web_search_tool" not in description
    assert "myrm_tools.session_store" in description

    static_pos = description.find("使用该工具执行")
    os_pos = description.find(get_os_hint().strip()[:20])
    ptc_pos = description.find("myrm_tools.notify")
    assert 0 <= static_pos < os_pos < ptc_pos

    registry_mod._registry = None


def test_native_tool_priority_section_still_directs_single_calls() -> None:
    assert "必须**使用 `file_read_tool`" in TOOL_DESCRIPTION
    assert "必须**使用 `glob_tool` / `grep_tool`" in TOOL_DESCRIPTION
    assert "myrm_tools.grep_tool" not in TOOL_DESCRIPTION


def test_legacy_misleading_ptc_examples_removed() -> None:
    assert "web_search_tool(query" not in TOOL_DESCRIPTION
    assert "file_read_tool(path" not in TOOL_DESCRIPTION
    assert "myrm_tools.web_fetch" not in TOOL_DESCRIPTION


def test_cross_call_persistence_mentions_session_store_separately() -> None:
    assert "session_load(key=...)" in TOOL_DESCRIPTION
    assert "Python**:每次执行独立进程" in TOOL_DESCRIPTION
