"""Tests for Plugin Sandbox Capability Tier model and static inference."""

from __future__ import annotations

import json
from myrm_agent_harness.agent.plugins import (
    AgentPluginParser,
    PluginCapabilityTier,
    PluginMcpServer,
    parse_manifest,
)
from myrm_agent_harness.agent.plugins.manifest import PLUGIN_SCHEMA
from myrm_agent_harness.agent.plugins.models import PluginParseResult


class TestPluginCapabilityTier:
    """Test PluginCapabilityTier model, manifest capabilities parsing, and inference."""

    def test_parse_manifest_declared_capabilities(self) -> None:
        manifest_dict = {
            "$schema": PLUGIN_SCHEMA,
            "name": "network-plugin",
            "capabilities": ["network", "read_only"],
        }
        meta, reported = parse_manifest(manifest_dict)
        assert meta.declared_capabilities == (
            PluginCapabilityTier.NETWORK,
            PluginCapabilityTier.READ_ONLY,
        )

    def test_manifest_invalid_capability_raises(self) -> None:
        import pytest
        from myrm_agent_harness.agent.plugins.manifest import ManifestSchemaValidationError

        manifest_dict = {
            "$schema": PLUGIN_SCHEMA,
            "name": "invalid-plugin",
            "capabilities": ["super_admin_unrestricted"],
        }
        with pytest.raises(ManifestSchemaValidationError, match="invalid capability"):
            parse_manifest(manifest_dict)

    def test_aggregated_capabilities_default_read_only(self) -> None:
        result = PluginParseResult()
        assert result.aggregated_capabilities == (PluginCapabilityTier.READ_ONLY,)

    def test_aggregated_capabilities_with_remote_server(self) -> None:
        remote_server = PluginMcpServer(
            name="weather",
            server_type="streamable_http",
            command=None,
            args=None,
            url="https://api.weather.com/mcp",
            headers=None,
            cwd=None,
            capabilities=(PluginCapabilityTier.NETWORK,),
        )
        result = PluginParseResult(servers=[remote_server])
        assert PluginCapabilityTier.NETWORK in result.aggregated_capabilities

    def test_aggregated_capabilities_with_stdio_server(self) -> None:
        stdio_server = PluginMcpServer(
            name="cli-tool",
            server_type="stdio",
            command="./bin/tool",
            args=["--run"],
            url=None,
            headers=None,
            cwd=None,
            capabilities=(
                PluginCapabilityTier.SHELL_EXEC,
                PluginCapabilityTier.FS_WRITE,
                PluginCapabilityTier.FS_READ,
            ),
        )
        result = PluginParseResult(servers=[stdio_server])
        assert PluginCapabilityTier.SHELL_EXEC in result.aggregated_capabilities
        assert PluginCapabilityTier.FS_WRITE in result.aggregated_capabilities

    def test_parse_files_infer_capabilities(self) -> None:
        parser = AgentPluginParser()
        files = {
            "plugin.json": json.dumps({
                "$schema": PLUGIN_SCHEMA,
                "name": "demo-stdio-plugin",
            }).encode("utf-8"),
            "mcp.json": json.dumps({
                "$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json",
                "mcpServers": {
                    "local_runner": {
                        "type": "stdio",
                        "command": "./tool.sh",
                    }
                },
            }).encode("utf-8"),
            "tool.sh": b"#!/bin/sh\necho hello",
        }
        res = parser.parse_files(files)
        assert res.meta is not None
        assert len(res.servers) == 1
        server = res.servers[0]
        assert PluginCapabilityTier.SHELL_EXEC in server.capabilities
        assert PluginCapabilityTier.SHELL_EXEC in res.aggregated_capabilities
