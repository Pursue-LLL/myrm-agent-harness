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

from .manifest import AgentPluginManifestMeta, decode_manifest_json, parse_manifest
from .mcp_config import decode_mcp_json, parse_mcp_servers, validate_mcp_top_level
from .parser import AgentPluginParser

__all__ = [
    "AgentPluginManifestMeta",
    "AgentPluginParser",
    "decode_manifest_json",
    "decode_mcp_json",
    "parse_manifest",
    "parse_mcp_servers",
    "validate_mcp_top_level",
]
