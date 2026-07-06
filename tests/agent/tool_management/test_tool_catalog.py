"""Tests for tool_catalog metadata SSOT."""

from __future__ import annotations

from myrm_agent_harness.agent.tool_management.tool_catalog import (
    ToolCatalogRole,
    build_tool_catalog_row,
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
