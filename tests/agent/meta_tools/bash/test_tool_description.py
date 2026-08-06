"""Static bash TOOL_DESCRIPTION prompt hygiene tests."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.bash._tool_description import TOOL_DESCRIPTION
from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import (
    create_bash_code_execute_tool,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_tool_helpers import get_os_hint


def test_tool_description_teaches_all_legal_execution_paths() -> None:
    assert "当前工具列表提供时" in TOOL_DESCRIPTION
    assert "原生工具" in TOOL_DESCRIPTION
    assert "from skills." in TOOL_DESCRIPTION
    assert "from tools." in TOOL_DESCRIPTION
    assert "tools.session_store" in TOOL_DESCRIPTION
    assert "``myrm_tools``" in TOOL_DESCRIPTION
    assert "普通对话的 Bash 中不可用" in TOOL_DESCRIPTION
    assert "myrm_tools.web_search_tool" not in TOOL_DESCRIPTION
    assert "myrm_tools.file_read_tool" not in TOOL_DESCRIPTION


def test_tool_description_module_exports() -> None:
    from myrm_agent_harness.agent.meta_tools.bash import _tool_description as mod

    assert mod.__all__ == ["TOOL_DESCRIPTION"]
    assert 2500 < len(TOOL_DESCRIPTION) < 5000


def test_create_bash_tool_static_description_only() -> None:
    bash_tool = create_bash_code_execute_tool()
    description = bash_tool.description

    assert description.startswith(TOOL_DESCRIPTION)
    assert get_os_hint() in description
    assert "## PTC" not in description
    assert "Turn1-bound tools" not in description
    assert "myrm_tools.web_search_tool" not in description
    assert "tools.session_store" in description

    static_pos = description.find("执行 Shell 命令")
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
    assert "场景 B" not in TOOL_DESCRIPTION
    assert "OBSERVATION-only bash" not in TOOL_DESCRIPTION
    assert "``timeout=120``" not in TOOL_DESCRIPTION
    assert "Skill 文档" in TOOL_DESCRIPTION or "对应 Skill" in TOOL_DESCRIPTION


def test_generic_ptc_merge_rules_documented() -> None:
    assert "Python PTC" in TOOL_DESCRIPTION
    assert "``asyncio.gather()``" in TOOL_DESCRIPTION
    assert "调用均必须 ``await``" in TOOL_DESCRIPTION
    assert "``[OBSERVATION]``" in TOOL_DESCRIPTION
    assert "[RESULT]" in TOOL_DESCRIPTION
    assert "file_write_tool" in TOOL_DESCRIPTION
    assert "func_a(...)" not in TOOL_DESCRIPTION
    assert "lookup_codes" not in TOOL_DESCRIPTION
    assert "BJP" not in TOOL_DESCRIPTION


def test_native_tool_priority_has_no_internal_rationale() -> None:
    assert "缺少验证与回滚" not in TOOL_DESCRIPTION
    assert "浪费交互轮次" not in TOOL_DESCRIPTION
    assert "## 原生工具优先" in TOOL_DESCRIPTION


def test_legacy_misleading_native_ptc_examples_removed() -> None:
    assert "web_search_tool(query" not in TOOL_DESCRIPTION
    assert "file_read_tool(path" not in TOOL_DESCRIPTION
    assert "myrm_tools.web_fetch" not in TOOL_DESCRIPTION


def test_cross_call_persistence_mentions_tools_session_store() -> None:
    assert "from tools.session_store import session_store" in TOOL_DESCRIPTION
    assert "from tools.session_load import session_load" in TOOL_DESCRIPTION
    assert "from tools.session_keys import session_keys" in TOOL_DESCRIPTION
    assert "调用均必须 ``await``" in TOOL_DESCRIPTION
    assert "256 KiB" in TOOL_DESCRIPTION
    assert "``session_keys`` 返回 ``list[str]``" in TOOL_DESCRIPTION
    assert "Python 每次独立执行" in TOOL_DESCRIPTION


def test_reason_requirement_documented() -> None:
    assert "reason" in TOOL_DESCRIPTION
    assert "≥10" in TOOL_DESCRIPTION


def test_background_contract_avoids_ptc_and_duplicate_output() -> None:
    assert "``run_in_background=true``" in TOOL_DESCRIPTION
    assert "Python PTC" in TOOL_DESCRIPTION
    assert "脚本只能前台执行" in TOOL_DESCRIPTION
    assert "``since_cursor``" in TOOL_DESCRIPTION
    assert "MYRM_PROGRESS" in TOOL_DESCRIPTION
    assert "MYRM_CHECKPOINT" in TOOL_DESCRIPTION
    assert "bash_process_tool" in TOOL_DESCRIPTION
    assert "write_stdin" in TOOL_DESCRIPTION
    assert "submit_stdin" in TOOL_DESCRIPTION
    assert "close_stdin" in TOOL_DESCRIPTION
    assert "SIGTERM" not in TOOL_DESCRIPTION
    assert "still_running" not in TOOL_DESCRIPTION
    assert "last_progress" not in TOOL_DESCRIPTION


def test_glob_routing_omits_nonexistent_depth_argument() -> None:
    assert "glob_tool" in TOOL_DESCRIPTION
    assert "限定 depth" not in TOOL_DESCRIPTION


def test_third_party_libs_follow_venv_not_hardcoded_preinstall() -> None:
    assert "项目环境" in TOOL_DESCRIPTION
    assert "pip install" in TOOL_DESCRIPTION
    assert "pandas" not in TOOL_DESCRIPTION
    assert "ModuleNotFoundError" not in TOOL_DESCRIPTION


def test_workspace_path_hint_documented() -> None:
    assert "/workspace/..." in TOOL_DESCRIPTION


def test_python_c_guidance_avoids_ambiguous_short_source() -> None:
    assert "python -c" in TOOL_DESCRIPTION
    assert "可能与 Shell 混淆" in TOOL_DESCRIPTION
    assert "python script.py" in TOOL_DESCRIPTION


def test_prompt_omits_implementation_noise_and_harmful_restrictions() -> None:
    assert "禁止写注释" not in TOOL_DESCRIPTION
    assert "ActivityCard" not in TOOL_DESCRIPTION
    assert "每会话最多 5" not in TOOL_DESCRIPTION
    assert "auto-detect" not in TOOL_DESCRIPTION
    assert "file-mode" not in TOOL_DESCRIPTION
    assert "危险或破坏性操作必须先确认" not in TOOL_DESCRIPTION
    assert "20 行以上" not in TOOL_DESCRIPTION
    assert "按 chat" not in TOOL_DESCRIPTION
    assert "内置 PTC 能力" not in TOOL_DESCRIPTION
    assert "框架也会自动抬高" not in TOOL_DESCRIPTION
    assert "SIGKILL" not in TOOL_DESCRIPTION
