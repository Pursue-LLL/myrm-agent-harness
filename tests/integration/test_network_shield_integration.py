"""Integration test for SSRF Shield + DLP Allowlist + Message Repair.

This test verifies that:
1. SSRF Shield blocks internal IPs (192.168.x.x, 127.0.0.1, etc.)
2. DLP Allowlist blocks unauthorized domains when enabled
3. DLP Allowlist allows authorized domains
4. Message Repair appends _vtx suffix to tool_call_id
5. All protections work together in a realistic Agent scenario
"""

import socket
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.tools import StructuredTool

from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.agent.tool_management.tool_layers import ToolLayer
from myrm_agent_harness.agent.tool_management.types import ToolSource
from myrm_agent_harness.core.security.guards.ssrf import (
    SSRFSecurityError,
    async_pin_url,
)
from myrm_agent_harness.core.security.guards.url_allowlist import URLAllowlistGuard


def mock_getaddrinfo(ip: str):
    """Create a mock for asyncio.get_running_loop().getaddrinfo."""
    mock_loop = AsyncMock()
    mock_loop.getaddrinfo.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]
    return patch("asyncio.get_running_loop", return_value=mock_loop)


class TestNetworkShieldIntegration:
    """Integration tests for SSRF + DLP + Message Repair."""

    @pytest.mark.asyncio
    async def test_dlp_allowlist_blocks_unauthorized_domain(self):
        """Test that DLP blocks unauthorized domains."""
        with mock_getaddrinfo("8.8.8.8"), URLAllowlistGuard.apply(["api.github.com"]):
            # Allowed domain should work
            safe_url, headers = await async_pin_url("https://api.github.com/users")
            assert safe_url == "https://8.8.8.8/users"
            assert headers == {"Host": "api.github.com"}

            # Unauthorized domain should be blocked
            with pytest.raises(SSRFSecurityError, match="Access to evil.com is blocked"):
                await async_pin_url("https://evil.com/steal")

    @pytest.mark.asyncio
    async def test_ssrf_blocks_internal_ips(self):
        """Test that SSRF blocks internal IPs even with no DLP."""
        with mock_getaddrinfo("192.168.1.100"), URLAllowlistGuard.apply(None):  # No DLP restrictions
            with pytest.raises(SSRFSecurityError, match="Access to internal network is blocked"):
                await async_pin_url("http://192.168.1.100/admin")

    @pytest.mark.asyncio
    async def test_ssrf_blocks_dns_rebinding(self):
        """Test that SSRF blocks DNS rebinding attacks."""
        with mock_getaddrinfo("127.0.0.1"), URLAllowlistGuard.apply(["evil-domain.com"]):
            # Even if the domain is in the allowlist, if it resolves to internal IP, it should be blocked
            with pytest.raises(SSRFSecurityError, match="Access to internal network is blocked"):
                await async_pin_url("http://evil-domain.com/flushall")

    @pytest.mark.asyncio
    async def test_tool_registry_with_allowed_domains(self):
        """Test that ToolRegistry correctly sets allowed_domains in session context."""
        from myrm_agent_harness.agent.middlewares._session_context import get_allowed_domains_map

        # Create a mock tool
        async def mock_tool(url: str) -> str:
            return f"Fetched: {url}"

        tool = StructuredTool.from_function(
            func=mock_tool,
            name="mock_http_tool",
            description="A mock HTTP tool",
        )

        # Register tool with allowed_domains
        registry = ToolRegistry()
        registry.register(
            tool,
            source=ToolSource.USER,  # Skill-based tools use USER source
            layer=ToolLayer.EXTENDED,  # User/extended tools
            allowed_domains=["api.github.com"],
        )

        # Resolve registry (this should set the allowed_domains_map)
        resolved_tools = registry.resolve()

        # Verify that the tool was registered
        assert len(resolved_tools) == 1
        assert resolved_tools[0].name == "mock_http_tool"

        # Verify that allowed_domains_map was set correctly
        domains_map = get_allowed_domains_map()
        assert "mock_http_tool" in domains_map
        assert domains_map["mock_http_tool"] == ["api.github.com"]

    def test_message_repair_tool_call_id_uniqueness(self):
        """Test that tool_call_id gets _vtx suffix for uniqueness."""
        from myrm_agent_harness.toolkits.llms.adapters.tool_call_parsers import _parse_openai_format

        # Simulate a response with duplicate tool_call_id (as some models might do)
        response_dict = {
            "tool_calls": [
                {"id": "call_abc123", "type": "function", "function": {"name": "tool1", "arguments": "{}"}},
                {"id": "call_abc123", "type": "function", "function": {"name": "tool2", "arguments": "{}"}},
            ]
        }

        parsed = _parse_openai_format(response_dict)

        # Verify that both tool_call_ids have _vtx suffix
        assert len(parsed) == 2
        assert "_vtx" in parsed[0]["id"]
        assert "_vtx" in parsed[1]["id"]
        # They should still be different (original ID + unique UUID)
        assert parsed[0]["id"] != parsed[1]["id"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
