"""Core bridge coordinator providing standard memory tool definitions and execution dispatch for external clients.

[INPUT]
- toolkits.memory.universal_mcp_bridge.types::ExternalClientKind, McpTransportKind,
  UniversalMemoryBridgeOptions (POS: Typed data contracts for the universal mcp bridge subsystem.)

[OUTPUT]
- UniversalMcpMemoryBridge: Core bridge coordinator providing standard memory tool definitions and execution
  dispatch for external clients.

[POS]
Core bridge coordinator providing standard memory tool definitions and execution dispatch for external
clients.
"""

import logging
import sys

from .types import (
    ExternalClientKind,
    McpTransportKind,
    UniversalMemoryBridgeOptions,
)

logger = logging.getLogger(__name__)


class UniversalMcpMemoryBridge:
    """Core bridge coordinator providing standard memory tool definitions and execution dispatch for external clients."""

    # Standard tool surface exposed to external AI assistants (Claude Code, Cursor, Cline, etc.)
    EXPOSED_TOOL_NAMES: tuple[str, ...] = (
        "memory_recall",
        "memory_store",
        "memory_list",
        "memory_manage",
    )

    def __init__(self, default_options: UniversalMemoryBridgeOptions | None = None) -> None:
        self.options: UniversalMemoryBridgeOptions = default_options or UniversalMemoryBridgeOptions()

    @classmethod
    def detect_host_python_interpreter(cls) -> str:
        """Return the absolute path of the current Python executable."""
        return sys.executable

    def get_tool_definitions(self) -> list[dict[str, object]]:
        """Return MCP-compliant tool schema definitions for external agents."""
        return [
            {
                "name": "memory_recall",
                "description": "Search and retrieve pertinent user memories, facts, preferences, and guidelines.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Semantic search query string"},
                        "limit": {"type": "integer", "description": "Maximum records to return", "default": 5},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "memory_store",
                "description": "Store a new user fact, technical decision, or operational guideline into the shared memory hub.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string", "description": "Information or guideline to remember"},
                        "domain": {"type": "string", "description": "Topic or context domain", "default": "general"},
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "memory_list",
                "description": "List recently stored or pinned memories for the active user.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "description": "Number of memories to list", "default": 10},
                    },
                },
            },
            {
                "name": "memory_manage",
                "description": "Archive, delete, or update an existing memory item by identifier.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "memory_id": {"type": "string", "description": "Identifier of the memory record"},
                        "action": {"type": "string", "enum": ["delete", "archive"], "description": "Management action"},
                    },
                    "required": ["memory_id", "action"],
                },
            },
        ]

    def build_client_bridge_command(
        self,
        client: ExternalClientKind,
        override_user_id: str | None = None,
    ) -> list[str]:
        """Construct the CLI command arguments to spawn the bridge process for a target client."""
        user = override_user_id or self.options.user_id
        py_bin = self.detect_host_python_interpreter()

        if self.options.transport == McpTransportKind.STDIO:
            return [
                py_bin,
                *self.options.server_module_args,
                "--user-id",
                user,
                "--client-origin",
                client.value,
            ]
        else:
            return [
                py_bin,
                *self.options.server_module_args,
                "--transport",
                "sse",
                "--host",
                self.options.host,
                "--port",
                str(self.options.port),
                "--user-id",
                user,
            ]
