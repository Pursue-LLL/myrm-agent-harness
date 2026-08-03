"""Static bash TOOL_DESCRIPTION prompt hygiene tests."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.bash._tool_description import TOOL_DESCRIPTION
from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import (
    create_bash_code_execute_tool,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_tool_helpers import get_os_hint


def test_tool_description_teaches_mcp_script_not_myrm_tools() -> None:
    assert "from skills." in TOOL_DESCRIPTION
    assert "from tools." in TOOL_DESCRIPTION
    assert "单次调用仍用 native tool" in TOOL_DESCRIPTION
    assert "import myrm_tools" in TOOL_DESCRIPTION
    assert "禁止" in TOOL_DESCRIPTION
    assert "myrm_tools.web_search_tool" not in TOOL_DESCRIPTION
    assert "myrm_tools.file_read_tool" not in TOOL_DESCRIPTION


def test_tool_description_module_exports() -> None:
    from myrm_agent_harness.agent.meta_tools.bash import _tool_description as mod

    assert mod.__all__ == ["TOOL_DESCRIPTION"]
    assert 1500 < len(TOOL_DESCRIPTION) < 3500


def test_create_bash_tool_static_description_only() -> None:
    bash_tool = create_bash_code_execute_tool()
    description = bash_tool.description

    assert description.startswith(TOOL_DESCRIPTION)
    assert get_os_hint() in description
    assert "## PTC" not in description
    assert "Turn1-bound tools" not in description
    assert "myrm_tools.web_search_tool" not in description
    assert "tools.session_store" in description

    static_pos = description.find("使用该工具执行")
    os_pos = description.find(get_os_hint().strip()[:20])
    assert 0 <= static_pos < os_pos
    assert description == TOOL_DESCRIPTION + get_os_hint()


def test_native_tool_priority_section_still_directs_single_calls() -> None:
    assert "`file_read_tool`" in TOOL_DESCRIPTION
    assert "`glob_tool`" in TOOL_DESCRIPTION
    assert "`grep_tool`" in TOOL_DESCRIPTION
    assert "myrm_tools.grep_tool" not in TOOL_DESCRIPTION


def test_legacy_misleading_ptc_examples_removed() -> None:
    assert "web_search_tool(query" not in TOOL_DESCRIPTION
    assert "file_read_tool(path" not in TOOL_DESCRIPTION
    assert "myrm_tools.web_fetch" not in TOOL_DESCRIPTION
    assert "asyncio.gather(func_a()" not in TOOL_DESCRIPTION


def test_cross_call_persistence_mentions_tools_session_store() -> None:
    assert "from tools.session_store import session_store" in TOOL_DESCRIPTION
    assert "session_load" in TOOL_DESCRIPTION
    assert "每次执行独立进程" in TOOL_DESCRIPTION


def test_reason_requirement_documented() -> None:
    assert "reason" in TOOL_DESCRIPTION
    assert "≥10" in TOOL_DESCRIPTION


def test_background_submit_stdin_documented() -> None:
    assert "submit_stdin" in TOOL_DESCRIPTION
    assert "data=..." in TOOL_DESCRIPTION


def test_workspace_path_hint_documented() -> None:
    assert "/workspace/..." in TOOL_DESCRIPTION


def test_all_bash_process_actions_documented() -> None:
    for action in ("list", "output", "wait", "kill", "write_stdin", "submit_stdin", "close_stdin"):
        assert f"action='{action}'" in TOOL_DESCRIPTION


def test_python_c_guidance_matches_auto_rewrite_behavior() -> None:
    assert "auto-detect" in TOOL_DESCRIPTION or "file-mode" in TOOL_DESCRIPTION
    assert "python -c" in TOOL_DESCRIPTION
