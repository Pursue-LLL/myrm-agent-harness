"""Agent Plugins 1.0.0 standard parser (framework-level, client-agnostic).

Parses portable plugin packages (plugin.json + skills/ + mcp.json) into
structured component records. Persistence is owned by the business layer.
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
