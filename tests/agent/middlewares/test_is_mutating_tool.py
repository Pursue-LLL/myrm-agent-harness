"""Tests for is_mutating_tool SSOT used by Cron post-run verification."""

from myrm_agent_harness.agent.middlewares.completion import is_mutating_tool
from myrm_agent_harness.core.security.tool_registry import (
    SafetyMetadata,
    register_ptc_safety_metadata,
)


def test_is_mutating_tool_detects_file_write_alias() -> None:
    assert is_mutating_tool("file_write_tool") is True


def test_is_mutating_tool_detects_bash_alias() -> None:
    assert is_mutating_tool("bash_code_execute_tool") is True


def test_is_mutating_tool_detects_browser_alias() -> None:
    assert is_mutating_tool("browser_navigate_tool") is True


def test_is_mutating_tool_detects_cron_manage_alias() -> None:
    assert is_mutating_tool("cron_manage_tool") is True


def test_is_mutating_tool_ignores_read_only_tools() -> None:
    assert is_mutating_tool("grep_tool") is False
    assert is_mutating_tool("file_read_tool") is False
    assert is_mutating_tool("web_search_tool") is False
    assert is_mutating_tool("web_fetch_tool") is False


def test_is_mutating_tool_detects_registry_mutating_tools() -> None:
    """Tools that can mutate state must never be stripped even when absent from
    the static alias list — the registry metadata is the authority."""
    assert is_mutating_tool("bash_process_tool") is True  # kill / stdin actions
    assert is_mutating_tool("complete_goal_tool") is True
    assert is_mutating_tool("memory_save_tool") is True
    assert is_mutating_tool("memory_manage_tool") is True
    # skill_market_tool 的 install/uninstall/install_from_url 写入技能库，
    # registry 只读标注但实为变异——必须保留，剥离会丢失安装/卸载副作用
    assert is_mutating_tool("skill_market_tool") is True


def test_is_mutating_tool_interaction_ui_carriers_not_effectful() -> None:
    """Interaction/UI carriers are registry read-only and do NOT mutate state —
    so `is_mutating_tool` (Cron effectful SSOT) must not classify them as
    effectful, otherwise every UI-rendering cron run triggers an unnecessary
    adversarial-reviewer pass."""
    assert is_mutating_tool("ask_question_tool") is False
    assert is_mutating_tool("request_directory_tool") is False
    assert is_mutating_tool("render_ui_tool") is False
    assert is_mutating_tool("update_ui_data_tool") is False
    assert is_mutating_tool("browser_ask_human_tool") is False


def test_is_mutating_tool_unknown_tool_fails_closed() -> None:
    """Unregistered tools are assumed mutating (fail-closed): stripping an
    unknown call could silently drop a side effect."""
    assert is_mutating_tool("canvas_tool") is True
    assert is_mutating_tool("some_unknown_tool") is True


def test_is_mutating_tool_mcp_readonly_annotated() -> None:
    """MCP tool with explicit readOnlyHint=True is safe to strip."""
    tool_name = "mcp__weather__get_temperature"
    register_ptc_safety_metadata(
        "mcp_weather_skill",
        tool_name,
        SafetyMetadata(is_read_only=True, is_concurrent_safe=True),
        {"readOnlyHint": True},
    )
    assert is_mutating_tool(tool_name) is False


def test_is_mutating_tool_mcp_unannotated_fail_closed() -> None:
    """Unregistered MCP tool defaults to non-read-only (fail-closed) → mutating."""
    assert is_mutating_tool("mcp__payments__charge_card") is True

