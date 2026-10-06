"""Agent Plugins 1.0.0 standard parser and writer (framework-level, client-agnostic).

[POS]
Framework-level plugin packaging — parses portable plugin packages
(plugin.json + skills/ + mcp.json + ai.myrm/ client data) into structured
component records, and writes the strict inverse (verified by parse-back).
Persistence is owned by the business layer, keeping the harness reusable.

[INPUT]
- plugin 包原始字节 / 目录（plugin.json、skills/、mcp.json、ai.myrm/）

[OUTPUT]
- AgentPluginParser: 插件解析器
- PluginBundleSpec / build_plugin_bundle: 插件包写出端（确定性 ZIP + 回读自检）
- AgentPluginManifestMeta: 清单元数据
- decode_manifest_json() / decode_mcp_json(): 清单与 MCP 配置解码
- plugin_identity() / is_valid_plugin_name() / is_excluded_path() / AGENT_STRUCTURAL_KEYS: 打包规则 SSOT
"""

from .exporter import AgentPluginPacker
from .integrity import (
    infer_server_capabilities,
    verify_mcp_server_artifacts,
    verify_plugin_capability_diff,
    verify_plugin_packaging_integrity,
)
from .manifest import decode_manifest_json, parse_manifest
from .mcp_config import decode_mcp_json, parse_mcp_servers, validate_mcp_top_level
from .models import (
    AgentPluginManifestMeta,
    PluginAgent,
    PluginCapabilityTier,
    PluginDiagnostic,
    PluginDiagnosticLevel,
    PluginMcpServer,
    PluginParseResult,
    PluginSkill,
)
from .parser import AgentPluginParser
from .rules import (
    AGENT_STRUCTURAL_KEYS,
    MAX_PLUGIN_ZIP_BYTES,
    MAX_TEMPLATE_FILE_BYTES,
    MAX_TOTAL_TEMPLATE_BYTES,
    MYRM_NAMESPACE,
    is_excluded_path,
    is_valid_plugin_name,
    plugin_identity,
)
from .writer import PluginBundleError, PluginBundleSpec, PluginPackageResult, build_plugin_bundle

__all__ = [
    "AGENT_STRUCTURAL_KEYS",
    "MAX_PLUGIN_ZIP_BYTES",
    "MAX_TEMPLATE_FILE_BYTES",
    "MAX_TOTAL_TEMPLATE_BYTES",
    "MYRM_NAMESPACE",
    "AgentPluginManifestMeta",
    "AgentPluginPacker",
    "AgentPluginParser",
    "PluginAgent",
    "PluginBundleError",
    "PluginBundleSpec",
    "PluginCapabilityTier",
    "PluginDiagnostic",
    "PluginDiagnosticLevel",
    "PluginMcpServer",
    "PluginPackageResult",
    "PluginParseResult",
    "PluginSkill",
    "build_plugin_bundle",
    "decode_manifest_json",
    "decode_mcp_json",
    "infer_server_capabilities",
    "is_excluded_path",
    "is_valid_plugin_name",
    "parse_manifest",
    "parse_mcp_servers",
    "plugin_identity",
    "validate_mcp_top_level",
    "verify_mcp_server_artifacts",
    "verify_plugin_capability_diff",
    "verify_plugin_packaging_integrity",
]
