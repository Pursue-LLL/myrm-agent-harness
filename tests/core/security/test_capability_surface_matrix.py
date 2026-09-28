"""Unit tests for CapabilitySurface and fine-grained permission matrix."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.security.config import (
    expand_capability_surface_permissions,
    parse_security_config,
)
from myrm_agent_harness.agent.security.engine import evaluate_tool_call
from myrm_agent_harness.core.security.tool_registry.registry import (
    TOOL_PERMISSION_MAP,
    resolve_permission_type,
)
from myrm_agent_harness.core.security.types import (
    CAPABILITY_SURFACE_PERMISSIONS,
    DEFAULT_RULESET,
    CapabilitySurface,
    PermissionAction,
    SecurityConfig,
)


def test_capability_surface_enum_and_mappings() -> None:
    """Verify all 6 core capability surfaces are defined with correct governance targets."""
    surfaces = list(CapabilitySurface)
    assert len(surfaces) == 6
    assert CapabilitySurface.KNOWLEDGE_READ in surfaces
    assert CapabilitySurface.KNOWLEDGE_WRITE in surfaces
    assert CapabilitySurface.WEB_EGRESS in surfaces
    assert CapabilitySurface.CANDIDATE_CREATE in surfaces
    assert CapabilitySurface.REMOTE_TOOLS in surfaces
    assert CapabilitySurface.LOCAL_FILESYSTEM in surfaces

    # Check mapping completeness
    for surface in surfaces:
        assert surface in CAPABILITY_SURFACE_PERMISSIONS
        assert len(CAPABILITY_SURFACE_PERMISSIONS[surface]) >= 1


def test_tool_permission_map_wiki_tools() -> None:
    """Verify wiki tools are mapped to dedicated knowledge permissions."""
    assert TOOL_PERMISSION_MAP["wiki_query_tool"] == "knowledge_read"
    assert TOOL_PERMISSION_MAP["wiki_apply_tool"] == "knowledge_write"
    assert TOOL_PERMISSION_MAP["wiki_ingest_tool"] == "knowledge_write"

    assert resolve_permission_type("wiki_query_tool") == "knowledge_read"
    assert resolve_permission_type("wiki_apply_tool") == "knowledge_write"
    assert resolve_permission_type("wiki_ingest_tool") == "knowledge_write"


def test_default_ruleset_knowledge_baseline() -> None:
    """Verify default baseline: knowledge_read is ALLOW, knowledge_write is ASK."""
    from myrm_agent_harness.agent.security.engine import evaluate

    # Read should be default ALLOW
    read_rule = evaluate("knowledge_read", "*", DEFAULT_RULESET)
    assert read_rule.action == PermissionAction.ALLOW

    # Write should be default ASK to prevent silent mutation
    write_rule = evaluate("knowledge_write", "*", DEFAULT_RULESET)
    assert write_rule.action == PermissionAction.ASK


def test_expand_capability_surface_permissions() -> None:
    """Verify expand_capability_surface_permissions fans out high-level surfaces."""
    raw = {
        "knowledge_write": "deny",
        "web_egress": "ask",
    }
    expanded = expand_capability_surface_permissions(raw)
    assert expanded["knowledge_write"] == "deny"
    assert expanded["wiki_apply_tool"] == "deny"
    assert expanded["wiki_ingest_tool"] == "deny"
    assert expanded["web_egress"] == "ask"
    assert expanded["net_fetch"] == "ask"
    assert expanded["web_search_tool"] == "ask"


def test_parse_security_config_capability_matrix() -> None:
    """Verify parse_security_config accepts capabilityMatrix."""
    config_dict = {
        "capabilityMatrix": {
            "knowledge_write": "deny",
            "knowledge_read": "allow",
            "web_egress": "deny",
        }
    }
    sec_config = parse_security_config(config_dict)
    assert sec_config is not None

    # Test evaluate_tool_call for knowledge_write (e.g. wiki_apply_tool)
    action, reason = evaluate_tool_call(
        permission="knowledge_write",
        tool_input={"title": "Notes", "content": "hello"},
        config=sec_config,
        tool_name="wiki_apply_tool",
    )
    assert action == PermissionAction.DENY

    # Test evaluate_tool_call for knowledge_read (e.g. wiki_query_tool)
    action, reason = evaluate_tool_call(
        permission="knowledge_read",
        tool_input={"query": "test query"},
        config=sec_config,
        tool_name="wiki_query_tool",
    )
    assert action == PermissionAction.ALLOW

    # Test evaluate_tool_call for web_egress (e.g. net_fetch)
    action, reason = evaluate_tool_call(
        permission="net_fetch",
        tool_input={"url": "https://example.com/api"},
        config=sec_config,
        tool_name="web_fetch_tool",
    )
    assert action == PermissionAction.DENY
