"""Public facade of the universal mcp bridge subsystem.

[INPUT]
- toolkits.memory.universal_mcp_bridge.bridge_runner::UniversalMcpMemoryBridge (POS: Core bridge coordinator
  providing standard memory tool definitions and execution dispatch for external clients.)
- toolkits.memory.universal_mcp_bridge.config_generator::ExternalClientConfigGenerator (POS: Generates
  plug-and-play MCP configuration snippets for external AI tools.)
- toolkits.memory.universal_mcp_bridge.types::ClientConfigSnippet, ExternalClientKind, McpTransportKind,
  UniversalMemoryBridgeOptions (POS: Typed data contracts for the universal mcp bridge subsystem.)

[OUTPUT]
- Package facade re-exporting 6 public names: ClientConfigSnippet, ExternalClientConfigGenerator,
  ExternalClientKind, McpTransportKind, UniversalMcpMemoryBridge, UniversalMemoryBridgeOptions

[POS]
Public facade of the universal mcp bridge subsystem.
"""

from .bridge_runner import UniversalMcpMemoryBridge
from .config_generator import ExternalClientConfigGenerator
from .types import (
    ClientConfigSnippet,
    ExternalClientKind,
    McpTransportKind,
    UniversalMemoryBridgeOptions,
)

__all__ = [
    "ClientConfigSnippet",
    "ExternalClientConfigGenerator",
    "ExternalClientKind",
    "McpTransportKind",
    "UniversalMcpMemoryBridge",
    "UniversalMemoryBridgeOptions",
]
