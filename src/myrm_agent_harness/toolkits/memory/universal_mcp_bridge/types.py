"""Typed data contracts for the universal mcp bridge subsystem.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- ExternalClientKind: External AI coding agent or companion client types.
- McpTransportKind: Supported MCP communication transport kinds.
- ClientConfigSnippet: Standardized configuration snippet for an external AI assistant client.
- UniversalMemoryBridgeOptions: Options for generating external client MCP configuration and bridge
  execution.

[POS]
Typed data contracts for the universal mcp bridge subsystem.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class ExternalClientKind(StrEnum):
    """External AI coding agent or companion client types."""

    CLAUDE_CODE = "claude_code"
    CURSOR = "cursor"
    VSCODE_CLINE = "vscode_cline"
    CODEBUDDY = "codebuddy"
    HERMES = "hermes"


class McpTransportKind(StrEnum):
    """Supported MCP communication transport kinds."""

    STDIO = "stdio"
    SSE = "sse"
    HTTP = "http"


@dataclass(frozen=True)
class ClientConfigSnippet:
    """Standardized configuration snippet for an external AI assistant client."""

    client_kind: ExternalClientKind
    transport: McpTransportKind
    target_config_file_path: str
    config_format: str  # "json" or "yaml"
    config_payload: dict[str, object]
    raw_content: str
    instructions: str


@dataclass(frozen=True)
class UniversalMemoryBridgeOptions:
    """Options for generating external client MCP configuration and bridge execution."""

    user_id: str = "default_user"
    host: str = "127.0.0.1"
    port: int = 8000
    server_binary_path: str = "python"
    server_module_args: list[str] = field(default_factory=lambda: ["-m", "myrm_agent_harness.toolkits.memory.agent_surface.mcp_server"])
    transport: McpTransportKind = McpTransportKind.STDIO
    custom_env: dict[str, str] = field(default_factory=dict)
