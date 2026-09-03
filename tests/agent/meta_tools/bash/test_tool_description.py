"""Static bash TOOL_DESCRIPTION prompt hygiene tests."""

from __future__ import annotations

from myrm_agent_harness.agent.meta_tools.bash._tool.helpers import get_os_hint
from myrm_agent_harness.agent.meta_tools.bash._tool.tool_description import (
    TOOL_DESCRIPTION,
    TOOL_DESCRIPTION_EN,
    TOOL_DESCRIPTION_ZH,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import (
    create_bash_code_execute_tool,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_process_tools import (
    create_bash_process_tool,
)


def test_tool_description_module_exports() -> None:
    from myrm_agent_harness.agent.meta_tools.bash._tool import tool_description as mod

    assert "TOOL_DESCRIPTION" in mod.__all__
    assert "TOOL_DESCRIPTION_EN" in mod.__all__
    assert "TOOL_DESCRIPTION_ZH" in mod.__all__
    assert "resolve_bash_code_execute_tool_description" in mod.__all__
    assert 2400 < len(TOOL_DESCRIPTION_ZH) < 5000
    assert 2000 < len(TOOL_DESCRIPTION_EN) < 6000


def test_create_bash_tool_static_description_only() -> None:
    bash_tool_default = create_bash_code_execute_tool()
    description_en = bash_tool_default.description

    assert description_en.startswith(TOOL_DESCRIPTION_EN)
    assert get_os_hint(locale="en") in description_en
    assert "## PTC" not in description_en
    assert "Turn1-bound tools" not in description_en
    assert "myrm_tools.web_search_tool" not in description_en
    assert "tools.session_store" not in description_en

    bash_tool_zh = create_bash_code_execute_tool(locale="zh-CN")
    description_zh = bash_tool_zh.description
    assert description_zh.startswith(TOOL_DESCRIPTION_ZH)
    assert get_os_hint(locale="zh-CN") in description_zh

    static_pos = description_zh.find("**Shell 命令**")
    os_pos = description_zh.find(get_os_hint(locale="zh-CN").strip()[:20])
    assert 0 <= static_pos < os_pos
    assert description_zh == TOOL_DESCRIPTION_ZH + get_os_hint(locale="zh-CN")


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


def test_failure_root_cause_guidance_documented() -> None:
    """失败处理引导：先读 stderr/错误提示定位根因，勿盲目重试同一命令."""
    assert "stderr" in TOOL_DESCRIPTION
    assert "盲目重试" in TOOL_DESCRIPTION
    assert "定位根因" in TOOL_DESCRIPTION
    assert "严禁在未调整参数或逻辑时连续重复执行" in TOOL_DESCRIPTION


def test_optimization_strategy_merge_control_flow_documented() -> None:
    """L74: Python 源码合并 + 控制流，避免与专用工具优先歧义的旧表述."""
    assert "多次操作合并进一次 Python 源码" in TOOL_DESCRIPTION
    assert "while/if/try" in TOOL_DESCRIPTION
    assert "避免多次往返调用" in TOOL_DESCRIPTION
    assert "替代多次工具调用" not in TOOL_DESCRIPTION
    assert "无需压缩或转义" in TOOL_DESCRIPTION


def test_optimization_strategy_output_summary_documented() -> None:
    """L75: 大数据用 Python 分析，只给摘要."""
    assert "只输出所需数据" in TOOL_DESCRIPTION
    assert "只给摘要" in TOOL_DESCRIPTION
    assert "CSV/JSON/日志" in TOOL_DESCRIPTION


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


def test_no_internal_module_name_leaked_to_prompt() -> None:
    """内部模块名 myrm_tools 不得泄漏进 prompt（此地无银反模式）."""
    assert "myrm_tools" not in TOOL_DESCRIPTION


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


def test_background_detail_authority_lives_in_process_tool_desc() -> None:
    """后台 action 细节只维护在 bash_process_tool 自身 desc,TOOL_DESCRIPTION 仅概要预告."""
    process_desc = create_bash_process_tool().description or ""
    assert "list" in process_desc
    assert "kill" in process_desc
    assert "close_stdin" in process_desc
    assert "详见其工具描述" in TOOL_DESCRIPTION


def test_glob_routing_omits_nonexistent_depth_argument() -> None:
    assert "glob_tool" in TOOL_DESCRIPTION
    assert "限定 depth" not in TOOL_DESCRIPTION
    assert 'pattern="*"' not in TOOL_DESCRIPTION


def test_native_tool_routing_defers_usage_to_tool_descriptions() -> None:
    assert "检索代码" not in TOOL_DESCRIPTION
    assert "参数与示例见各工具描述" in TOOL_DESCRIPTION


def test_bash_positive_routing_covers_runtime_ops() -> None:
    routing = TOOL_DESCRIPTION.split("## 编写原则", maxsplit=1)[0]
    assert "curl" in routing
    assert "后台长任务" in routing
    assert "读文件/搜内容/列目录用上节专用工具" in routing


def test_preinstalled_third_party_libs_listed() -> None:
    assert "pandas" in TOOL_DESCRIPTION
    assert "numpy" in TOOL_DESCRIPTION


def test_workspace_path_hint_documented() -> None:
    assert "/workspace/..." in TOOL_DESCRIPTION


def test_python_c_wrapper_discouraged() -> None:
    assert "python -c" in TOOL_DESCRIPTION
    assert "python script.py" in TOOL_DESCRIPTION


def test_prompt_leaks_no_internal_impl_or_cross_language_schema() -> None:
    assert "文件模式" not in TOOL_DESCRIPTION
    assert "框架自动识别" not in TOOL_DESCRIPTION
    assert "TS 类型" not in TOOL_DESCRIPTION
    assert "TS类型" not in TOOL_DESCRIPTION
    assert "TypeScript" not in TOOL_DESCRIPTION


def test_capabilities_section_documents_combo_modes() -> None:
    """能力段枚举管道/组合形态; merge/OBSERVATION 判定细则只在编写原则."""
    capabilities_end = TOOL_DESCRIPTION.index("## 优先使用专用工具")
    capabilities = TOOL_DESCRIPTION[:capabilities_end]
    assert "组合执行" in capabilities
    assert "管道思想" in capabilities
    assert "技能批量" in capabilities
    assert "`&&`" in capabilities
    assert "`|`" in capabilities
    assert "见 #2" in capabilities
    assert "编写原则" in capabilities
    assert "多轮 Shell 持久" not in capabilities
    assert capabilities.count("依赖性分析") == 0
    assert "asyncio.gather" not in capabilities
    assert "判定标准" not in capabilities
    assert "组合调用能力或方法以提效" not in capabilities
    assert "组合调用工具或方法以提效" not in capabilities


def test_async_section_documents_why_and_links_to_gather_examples() -> None:
    assert "技能/MCP 调用为 async" in TOOL_DESCRIPTION
    assert "必须 await" in TOOL_DESCRIPTION
    assert "写法见上方示例" in TOOL_DESCRIPTION


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


def test_bash_process_pid_field_guides_integer_type() -> None:
    """pid must be an integer — a string job id triggers schema ValidationError."""
    from myrm_agent_harness.agent.meta_tools.bash.bash_process_tools import (
        _BashProcessInput,
    )

    pid_desc = _BashProcessInput.model_fields["pid"].description or ""
    assert "do not pass a string" in pid_desc
    json_schema = _BashProcessInput.model_json_schema()
    types = {t.get("type") for t in json_schema["properties"]["pid"].get("anyOf", [])}
    assert "integer" in types


def test_bash_process_and_execute_prompts_share_stdin_contract() -> None:
    process_desc = create_bash_process_tool().description or ""
    for keyword in ("waiting_for_input", "input_wait_hint", "submit_stdin"):
        assert keyword in TOOL_DESCRIPTION
        assert keyword in process_desc
