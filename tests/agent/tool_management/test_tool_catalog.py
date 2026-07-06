"""Tests for tool_catalog metadata SSOT."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.tool_management.tool_catalog import (
    ToolCatalogRole,
    build_tool_catalog_row,
    build_tool_catalog_rows,
    format_tool_catalog_markdown,
    get_tool_catalog_role,
    get_tool_load_condition,
    get_tool_product_id,
    validate_tool_catalog,
)
from myrm_agent_harness.agent.tool_management.tool_layers import ToolLayer


def test_orchestration_signal_roles() -> None:
    assert get_tool_catalog_role("dispatch_research") is ToolCatalogRole.ORCHESTRATION_SIGNAL
    assert get_tool_catalog_role("submit_verdict") is ToolCatalogRole.ORCHESTRATION_SIGNAL


def test_runtime_hook_role() -> None:
    assert get_tool_catalog_role("_completion_check") is ToolCatalogRole.RUNTIME_HOOK


def test_default_user_capability_role() -> None:
    assert get_tool_catalog_role("web_search_tool") is ToolCatalogRole.USER_CAPABILITY


def test_product_id_mapping() -> None:
    assert get_tool_product_id("web_search_tool") == "web_search"
    assert get_tool_product_id("bash_code_execute_tool") is None
    assert get_tool_product_id("web_fetch_tool") is None
    assert get_tool_product_id("canvas_batch_layout") == "canvas"
    assert get_tool_product_id("cron_manage_tool") == "cron"


def test_load_condition_override() -> None:
    condition = get_tool_load_condition("web_search_tool", layer=ToolLayer.COMMON)
    assert "web_search" in condition


def test_build_tool_catalog_row() -> None:
    row = build_tool_catalog_row("think", layer=ToolLayer.EXTENDED)
    assert row.role is ToolCatalogRole.ORCHESTRATION_SIGNAL
    assert row.layer is ToolLayer.EXTENDED


def test_load_condition_uses_product_id_fallback() -> None:
    condition = get_tool_load_condition("browser_navigate_tool", layer=ToolLayer.EXTENDED)
    assert condition == "enabled_builtin_tools: browser"


def test_validate_rejects_wrong_orchestration_role() -> None:
    from myrm_agent_harness.agent.tool_management import tool_catalog as catalog_module

    original = dict(catalog_module._ROLE_OVERRIDES)
    try:
        catalog_module._ROLE_OVERRIDES["dispatch_research"] = ToolCatalogRole.USER_CAPABILITY
        errors = validate_tool_catalog({"dispatch_research": ToolLayer.EXTENDED})
        assert any("dispatch_research" in err for err in errors)
    finally:
        catalog_module._ROLE_OVERRIDES.clear()
        catalog_module._ROLE_OVERRIDES.update(original)


def test_conversation_history_group_without_override_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from myrm_agent_harness.agent.tool_management import tool_catalog as catalog_module

    monkeypatch.setitem(
        catalog_module.TOOL_TO_GROUP,
        "future_conv_tool",
        "conversation_history",
    )
    assert get_tool_product_id("future_conv_tool") is None


def test_load_condition_default_by_layer() -> None:
    condition = get_tool_load_condition("unknown_future_tool", layer=ToolLayer.CORE)
    assert "Agent baseline" in condition


def test_build_tool_catalog_rows_sorts_and_coerces_str_layer() -> None:
    rows = build_tool_catalog_rows(
        {
            "web_search_tool": "COMMON",
            "bash_code_execute_tool": ToolLayer.CORE,
        }
    )
    assert rows[0].name == "bash_code_execute_tool"
    assert rows[0].layer is ToolLayer.CORE
    assert rows[-1].name == "web_search_tool"


def test_validate_rejects_underscore_user_capability() -> None:
    errors = validate_tool_catalog({"_ghost_tool": ToolLayer.EXTENDED})
    assert any("_ghost_tool" in err for err in errors)


def test_validate_rejects_wrong_completion_check_role() -> None:
    from myrm_agent_harness.agent.tool_management import tool_catalog as catalog_module

    original = dict(catalog_module._ROLE_OVERRIDES)
    try:
        catalog_module._ROLE_OVERRIDES["_completion_check"] = ToolCatalogRole.USER_CAPABILITY
        errors = validate_tool_catalog({"_completion_check": ToolLayer.EXTENDED})
        assert any("_completion_check" in err for err in errors)
    finally:
        catalog_module._ROLE_OVERRIDES.clear()
        catalog_module._ROLE_OVERRIDES.update(original)


def test_format_tool_catalog_markdown_renders_table() -> None:
    row = build_tool_catalog_row("web_search_tool", layer=ToolLayer.COMMON)
    table = format_tool_catalog_markdown([row])
    assert "| Tool | Layer | Role | Product ID | Load condition |" in table
    assert "`web_search_tool`" in table
    assert "web_search" in table
