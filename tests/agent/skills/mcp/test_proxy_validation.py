"""Tests for MCP proxy required-argument validation."""

from __future__ import annotations

from myrm_agent_harness.agent.skills.mcp.proxy_service import _validate_required_mcp_params


class TestValidateRequiredMcpParams:
    def test_missing_required_returns_error_payload(self) -> None:
        schema_entry = {
            "description": "Create issue",
            "inputSchema": {
                "type": "object",
                "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
                "required": ["title"],
            },
        }
        result = _validate_required_mcp_params("create_issue", {}, schema_entry)
        assert result is not None
        assert "missing required argument" in str(result.get("error"))
        assert result.get("parameters") is not None

    def test_all_required_present_returns_none(self) -> None:
        schema_entry = {
            "inputSchema": {
                "type": "object",
                "properties": {"title": {"type": "string"}},
                "required": ["title"],
            },
        }
        assert _validate_required_mcp_params("create_issue", {"title": "bug"}, schema_entry) is None

    def test_no_required_field_returns_none(self) -> None:
        schema_entry = {"inputSchema": {"type": "object", "properties": {}}}
        assert _validate_required_mcp_params("ping", {}, schema_entry) is None
