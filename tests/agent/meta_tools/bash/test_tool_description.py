"""Static bash TOOL_DESCRIPTION prompt hygiene tests."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.bash._tool_description import TOOL_DESCRIPTION
from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import (
    create_bash_code_execute_tool,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_process_tools import (
    create_bash_process_tool,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_tool_helpers import get_os_hint


def test_tool_description_module_exports() -> None:
    from myrm_agent_harness.agent.meta_tools.bash import _tool_description as mod

    assert mod.__all__ == ["TOOL_DESCRIPTION"]
    assert 2400 < len(TOOL_DESCRIPTION) < 5000


def test_create_bash_tool_static_description_only() -> None:
    bash_tool = create_bash_code_execute_tool()
    description = bash_tool.description

    assert description.startswith(TOOL_DESCRIPTION)
    assert get_os_hint() in description
    assert "## PTC" not in description
    assert "Turn1-bound tools" not in description
    assert "myrm_tools.web_search_tool" not in description
    assert "tools.session_store" not in description

    static_pos = description.find("**Shell 命令**")
    os_pos = description.find(get_os_hint().strip()[:20])
    assert 0 <= static_pos < os_pos
    assert description == TOOL_DESCRIPTION + get_os_hint()


def test_native_tool_priority_section_still_directs_single_calls() -> None:
    assert "`file_read_tool`" in TOOL_DESCRIPTION
    assert "`glob_tool`" in TOOL_DESCRIPTION
    assert "`grep_tool`" in TOOL_DESCRIPTION
    assert "myrm_tools.grep_tool" not in TOOL_DESCRIPTION


def test_bash_description_is_decoupled_from_mcp_skill_sop() -> None:
    """MCP workflow belongs in Skill docs, not bash tool description."""
    assert "/mcp/" not in TOOL_DESCRIPTION
    assert "skill_select_tool" not in TOOL_DESCRIPTION
    assert "MCP Skill" not in TOOL_DESCRIPTION
    assert "from skills." not in TOOL_DESCRIPTION
    assert "from tools." not in TOOL_DESCRIPTION
    assert "tools.session_store" not in TOOL_DESCRIPTION


def test_large_output_eviction_read_hint_documented() -> None:
    assert "file_read_tool" in TOOL_DESCRIPTION
    assert ".context/.../evicted/" in TOOL_DESCRIPTION


def test_merge_rules_and_output_format_documented() -> None:
    assert "asyncio.gather" in TOOL_DESCRIPTION
    assert "[OBSERVATION]" in TOOL_DESCRIPTION
    assert "[RESULT]" in TOOL_DESCRIPTION
    assert "file_write_tool" in TOOL_DESCRIPTION
    assert "func_a(...)" not in TOOL_DESCRIPTION
    assert "lookup_codes" not in TOOL_DESCRIPTION
    assert "BJP" not in TOOL_DESCRIPTION


def test_cross_call_persistence_uses_workspace_files_not_session_store() -> None:
    assert "tools.session_store" not in TOOL_DESCRIPTION
    assert "session_load" not in TOOL_DESCRIPTION
    assert "session_keys" not in TOOL_DESCRIPTION
    assert "json.dump" in TOOL_DESCRIPTION or "json.dump/load" in TOOL_DESCRIPTION
    assert "file_write_tool" in TOOL_DESCRIPTION
    assert "禁止" in TOOL_DESCRIPTION and "[RESULT]" in TOOL_DESCRIPTION
    assert "优先一次 bash 合并" in TOOL_DESCRIPTION


def test_myrm_tools_blocked_in_prompt() -> None:
    assert "myrm_tools" in TOOL_DESCRIPTION
    assert "myrm_tools.web_search_tool" not in TOOL_DESCRIPTION


def test_background_contract_documented() -> None:
    assert "run_in_background=true" in TOOL_DESCRIPTION
    assert "since_cursor" in TOOL_DESCRIPTION
    assert "waiting_for_input" in TOOL_DESCRIPTION
    assert "input_wait_hint" in TOOL_DESCRIPTION
    assert TOOL_DESCRIPTION.count("waiting_for_input") >= 2
    assert "MYRM_PROGRESS" in TOOL_DESCRIPTION
    assert "MYRM_CHECKPOINT" in TOOL_DESCRIPTION
    assert "bash_process_tool" in TOOL_DESCRIPTION
    assert "write_stdin" in TOOL_DESCRIPTION
    assert "submit_stdin" in TOOL_DESCRIPTION
    assert "close_stdin" in TOOL_DESCRIPTION
    assert "SIGTERM" not in TOOL_DESCRIPTION
    assert "still_running" not in TOOL_DESCRIPTION


def test_glob_routing_omits_nonexistent_depth_argument() -> None:
    assert "glob_tool" in TOOL_DESCRIPTION
    assert "限定 depth" not in TOOL_DESCRIPTION


def test_preinstalled_third_party_libs_listed() -> None:
    assert "pandas" in TOOL_DESCRIPTION
    assert "numpy" in TOOL_DESCRIPTION


def test_workspace_path_hint_documented() -> None:
    assert "/workspace/..." in TOOL_DESCRIPTION


def test_python_c_wrapper_discouraged() -> None:
    assert "python -c" in TOOL_DESCRIPTION
    assert "python script.py" in TOOL_DESCRIPTION


def test_capabilities_section_has_no_redundant_merge_bullet() -> None:
    """Merge/OBSERVATION rules live under 编写原则; do not duplicate in 能力."""
    capabilities_end = TOOL_DESCRIPTION.index("## 优先使用专用工具")
    capabilities = TOOL_DESCRIPTION[:capabilities_end]
    assert "组合调用能力或方法以提效" not in capabilities
    assert capabilities.count("依赖性分析") == 0


def test_shell_commands_include_common_ops() -> None:
    assert "mv/cp/rm" in TOOL_DESCRIPTION


def test_reason_not_duplicated_in_static_prompt() -> None:
    """reason lives in BashInput schema, not static TOOL_DESCRIPTION."""
    assert "≥10" not in TOOL_DESCRIPTION


def test_bash_process_tool_description_documents_waiting_for_input() -> None:
    tool = create_bash_process_tool()
    desc = tool.description or ""
    assert "waiting_for_input" in desc
    assert "input_wait_hint" in desc
    assert "submit_stdin" in desc
    assert "blind-poll" in desc


def test_bash_process_and_execute_prompts_share_stdin_contract() -> None:
    process_desc = create_bash_process_tool().description or ""
    for keyword in ("waiting_for_input", "input_wait_hint", "submit_stdin"):
        assert keyword in TOOL_DESCRIPTION
        assert keyword in process_desc
