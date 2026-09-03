"""Tests for unified locale handling across all LLM meta tools in harness."""

from __future__ import annotations

from unittest.mock import MagicMock

from myrm_agent_harness.agent.config.file_io import FileIOConfig
from myrm_agent_harness.agent.meta_tools import get_meta_tools
from myrm_agent_harness.agent.meta_tools.answer_user_tool import (
    create_answer_user_tool,
    resolve_answer_user_tool_description,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import (
    create_bash_code_execute_tool,
)
from myrm_agent_harness.agent.meta_tools.bash.bash_process_tools import (
    create_bash_process_tool,
    resolve_bash_process_tool_description,
)
from myrm_agent_harness.agent.meta_tools.discover_capability.discover_capability_tool import (
    create_discover_capability_tool,
)
from myrm_agent_harness.agent.meta_tools.file_ops.file_edit_tool import (
    create_file_edit_tool,
    resolve_file_edit_tool_description,
)
from myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool import (
    create_file_read_tool,
    resolve_file_read_tool_description,
)
from myrm_agent_harness.agent.meta_tools.file_ops.file_write_tool import (
    create_file_write_tool,
    resolve_file_write_tool_description,
)
from myrm_agent_harness.agent.meta_tools.file_search.glob_tool import (
    create_glob_tool,
    resolve_glob_tool_description,
)
from myrm_agent_harness.agent.meta_tools.file_search.grep_tool import (
    create_grep_tool,
    resolve_grep_tool_description,
)
from myrm_agent_harness.agent.meta_tools.skills.manage.skill_manage_tool import (
    create_skill_manage_tool,
    resolve_skill_manage_tool_description,
)
from myrm_agent_harness.agent.meta_tools.skills.market.skill_market_tool import (
    create_skill_market_tool,
    resolve_skill_market_tool_description,
)
from myrm_agent_harness.agent.meta_tools.skills.select.skill_select_tool import (
    build_skill_select_static_description,
    create_select_skill_tool,
)
from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.agent.types import AgentRuntimeConfig, AgentRuntimeSpec


def test_file_ops_descriptions_locale_resolution() -> None:
    # File Read
    assert "Read file contents" in resolve_file_read_tool_description(None)
    assert "Read file contents" in resolve_file_read_tool_description("en")
    assert "读取文件内容" in resolve_file_read_tool_description("zh-CN")

    tool_en = create_file_read_tool(locale="en")
    assert "Read file contents" in tool_en.description
    tool_zh = create_file_read_tool(locale="zh-CN")
    assert "读取文件内容" in tool_zh.description

    # File Write
    assert "Create a new file" in resolve_file_write_tool_description(None)
    assert "创建新文件" in resolve_file_write_tool_description("zh-CN")
    write_tool_en = create_file_write_tool()
    assert "Create a new file" in write_tool_en.description
    write_tool_zh = create_file_write_tool(locale="zh-CN")
    assert "创建新文件" in write_tool_zh.description

    # File Edit
    assert "Accurately edit file" in resolve_file_edit_tool_description(None)
    assert "精确编辑文件内容" in resolve_file_edit_tool_description("zh-CN")
    edit_tool_en = create_file_edit_tool()
    assert "Accurately edit file" in edit_tool_en.description
    edit_tool_zh = create_file_edit_tool(locale="zh-CN")
    assert "精确编辑文件内容" in edit_tool_zh.description


def test_file_search_descriptions_locale_resolution() -> None:
    io_cfg = FileIOConfig()
    # Glob
    assert "Search for matching files" in resolve_glob_tool_description(io_cfg, None)
    assert "搜索匹配的文件" in resolve_glob_tool_description(io_cfg, "zh-CN")
    glob_tool_en = create_glob_tool()
    assert "Search for matching files" in glob_tool_en.description
    glob_tool_zh = create_glob_tool(locale="zh-CN")
    assert "搜索匹配的文件" in glob_tool_zh.description

    # Grep
    assert "Search file contents" in resolve_grep_tool_description(io_cfg, None)
    assert "搜索文件内容" in resolve_grep_tool_description(io_cfg, "zh-CN")
    grep_tool_en = create_grep_tool()
    assert "Search file contents" in grep_tool_en.description
    grep_tool_zh = create_grep_tool(locale="zh-CN")
    assert "搜索文件内容" in grep_tool_zh.description


def test_bash_tools_descriptions_locale_resolution() -> None:
    # Bash execute
    bash_en = create_bash_code_execute_tool(locale="en")
    assert "Execute Shell commands" in bash_en.description
    assert "OS:" in bash_en.description

    bash_zh = create_bash_code_execute_tool(locale="zh-CN")
    assert "使用该工具执行准确的 Shell 命令" in bash_zh.description
    assert "## 当前系统" in bash_zh.description

    # Bash process
    assert "Manage background bash processes" in resolve_bash_process_tool_description(None)
    assert "管理通过 bash_code_execute_tool" in resolve_bash_process_tool_description("zh-CN")
    proc_en = create_bash_process_tool()
    assert "Manage background bash processes" in proc_en.description
    proc_zh = create_bash_process_tool(locale="zh-CN")
    assert "管理通过 bash_code_execute_tool" in proc_zh.description


def test_skill_meta_tools_descriptions_locale_resolution() -> None:
    # Skill Select
    assert "Select bound skills" in build_skill_select_static_description(None)
    assert "选择已绑定的技能" in build_skill_select_static_description("zh-CN")
    backend = MagicMock()
    select_en = create_select_skill_tool([], backend)
    assert "Select bound skills" in select_en.description
    select_zh = create_select_skill_tool([], backend, locale="zh-CN")
    assert "选择已绑定的技能" in select_zh.description

    # Skill Manage
    assert "Manage skills" in resolve_skill_manage_tool_description(None)
    assert "管理技能" in resolve_skill_manage_tool_description("zh-CN")
    write_backend = MagicMock()
    manage_en = create_skill_manage_tool(write_backend, backend)
    assert "Manage skills" in manage_en.description
    manage_zh = create_skill_manage_tool(write_backend, backend, locale="zh-CN")
    assert "管理技能" in manage_zh.description

    # Skill Market
    assert "Install NEW skills" in resolve_skill_market_tool_description(None)
    assert "从外部市场" in resolve_skill_market_tool_description("zh-CN")
    market_backend = MagicMock()
    market_en = create_skill_market_tool(market_backend)
    assert "Install NEW skills" in market_en.description
    market_zh = create_skill_market_tool(market_backend, locale="zh-CN")
    assert "从外部市场" in market_zh.description

    # Discover capability
    disc_en = create_discover_capability_tool()
    assert "Search for missing capabilities" in disc_en.description
    disc_zh = create_discover_capability_tool(locale="zh-CN")
    assert "在当前 Agent 已绑定的技能库" in disc_zh.description


def test_answer_user_tool_locale_resolution() -> None:
    assert "Call only when you can confidently deliver" in resolve_answer_user_tool_description(None)
    assert "仅在当你可以自信地提供完美的满分答案时调用" in resolve_answer_user_tool_description("zh-CN")

    ans_en = create_answer_user_tool(locale="en")
    assert "Call only when you can confidently deliver" in ans_en.description
    ans_zh = create_answer_user_tool(locale="zh-CN")
    assert "仅在当你可以自信地提供完美的满分答案时调用" in ans_zh.description


def test_get_meta_tools_passes_locale() -> None:
    # EN (default)
    registry_en = ToolRegistry()
    tools_en = get_meta_tools(
        skills=[],
        registry=registry_en,
        enable_shell_tools=True,
        enable_answer_tool=True,
        locale="en",
    )
    descriptions_en = {t.name: t.description for t in tools_en}
    assert "Read file contents" in descriptions_en["file_read_tool"]
    assert "Create a new file" in descriptions_en["file_write_tool"]
    assert "Accurately edit file" in descriptions_en["file_edit_tool"]
    assert "Search for matching files" in descriptions_en["glob_tool"]
    assert "Search file contents" in descriptions_en["grep_tool"]
    assert "Execute Shell commands" in descriptions_en["bash_code_execute_tool"]
    assert "Manage background bash processes" in descriptions_en["bash_process_tool"]
    assert "Call only when you can confidently deliver" in descriptions_en["request_answer_user_tool"]

    # ZH
    registry_zh = ToolRegistry()
    tools_zh = get_meta_tools(
        skills=[],
        registry=registry_zh,
        enable_shell_tools=True,
        enable_answer_tool=True,
        locale="zh-CN",
    )
    descriptions_zh = {t.name: t.description for t in tools_zh}
    assert "读取文件内容" in descriptions_zh["file_read_tool"]
    assert "创建新文件" in descriptions_zh["file_write_tool"]
    assert "精确编辑文件内容" in descriptions_zh["file_edit_tool"]
    assert "搜索匹配的文件" in descriptions_zh["glob_tool"]
    assert "搜索文件内容" in descriptions_zh["grep_tool"]
    assert "使用该工具执行准确的 Shell 命令" in descriptions_zh["bash_code_execute_tool"]
    assert "管理通过 bash_code_execute_tool" in descriptions_zh["bash_process_tool"]
    assert "仅在当你可以自信地提供完美的满分答案时调用" in descriptions_zh["request_answer_user_tool"]


def test_agent_runtime_spec_and_config_prompt_locale() -> None:
    spec = AgentRuntimeSpec(
        agent_id="test-agent",
        name="Test",
        system_prompt="Test prompt",
        locale="zh-CN",
        prompt_locale="en",
    )
    assert spec.locale == "zh-CN"
    assert spec.prompt_locale == "en"

    config = AgentRuntimeConfig(
        locale="zh-CN",
        prompt_locale="en",
    )
    assert config.locale == "zh-CN"
    assert config.prompt_locale == "en"
