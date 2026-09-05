"""Agent Plugins 1.0.0 standard parser (framework-level, client-agnostic).

[POS]
Framework-level plugin parsing — parses portable plugin packages
(plugin.json + skills/ + mcp.json) into structured component records.
Persistence is owned by the business layer, keeping the harness reusable.

[INPUT]
- plugin 包原始字节 / 目录（plugin.json、skills/、mcp.json）

[OUTPUT]
- AgentPluginParser: 插件解析器
- AgentPluginManifestMeta: 清单元数据
- decode_manifest_json() / decode_mcp_json(): 清单与 MCP 配置解码
"""

from .exporter import AgentPluginPacker, PluginPackageResult, canonical_plugin_name
from .integrity import (
    infer_server_capabilities,
    verify_mcp_server_artifacts,
    verify_plugin_capability_diff,
    verify_plugin_packaging_integrity,
)
from .manifest import AgentPluginManifestMeta, decode_manifest_json, parse_manifest
from .mcp_config import decode_mcp_json, parse_mcp_servers, validate_mcp_top_level
from .models import (
    PluginAgent,
    PluginCapabilityTier,
    PluginDiagnostic,
    PluginDiagnosticLevel,
    PluginMcpServer,
    PluginParseResult,
    PluginSkill,
)
from .parser import AgentPluginParser

__all__ = [
    "AgentPluginManifestMeta",
    "AgentPluginPacker",
    "AgentPluginParser",
    "PluginAgent",
    "PluginCapabilityTier",
    "PluginDiagnostic",
    "PluginDiagnosticLevel",
    "PluginMcpServer",
    "PluginPackageResult",
    "PluginParseResult",
    "PluginSkill",
    "canonical_plugin_name",
    "decode_manifest_json",
    "decode_mcp_json",
    "infer_server_capabilities",
    "parse_manifest",
    "parse_mcp_servers",
    "validate_mcp_top_level",
    "verify_mcp_server_artifacts",
    "verify_plugin_capability_diff",
    "verify_plugin_packaging_integrity",
]
