"""MCP Configuration.

MCP server configuration models passed to the Agent.

[INPUT]
- (none)

[OUTPUT]
- MCPAuthProvider: Authentication provider protocol for remote MCP servers.
- MCPConfig: MCP server configuration (SSE, Stdio, Streamable HTTP).
- should_register_mcp_tool: Per-server include/exclude filter for MCP tool whitelisting.
- sanitize_mcp_name_component: Sanitize name component for ``mcp__{server}__{tool}`` generation (replaces non-alnum, collapses consecutive underscores, strips leading/trailing underscores, falls back to 'unnamed').
- is_mcp_tool_name: Check if a tool name follows the ``mcp__{server}__{tool}`` convention.
- parse_mcp_tool_name: Parse ``mcp__{server}__{tool}`` into (server, tool) tuple.

[POS]
MCP Configuration
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field, model_validator


@runtime_checkable
class MCPAuthProvider(Protocol):
    """Authentication provider for remote MCP servers.

    Framework-level Protocol — business layer injects concrete implementations
    (e.g. OAuth 2.0 + PKCE, API key, custom token exchange).

    The provider is called once before each MCP connection attempt.
    Returned headers are merged into the HTTP request headers.
    """

    async def get_auth_headers(self, server_name: str, server_url: str) -> dict[str, str]:
        """Return authentication headers for the given MCP server.

        Args:
            server_name: Unique MCP server identifier from MCPConfig.name
            server_url: Target URL for SSE/HTTP connections

        Returns:
            Dict of HTTP headers (e.g. {"Authorization": "Bearer <token>"}).
            Return empty dict if no auth is needed.
        """
        ...


class MCPConfig(BaseModel):
    """MCP server configuration passed to the Agent.

    Supports three transport types:
    - SSE: Server-Sent Events (HTTP)
    - Stdio: Standard I/O
    - Streamable HTTP

    Attributes:
        name: Unique server identifier
        type: Transport type (sse, stdio, streamable_http)
        url: URL for SSE/HTTP connections (required when type=sse/streamable_http)
        command: Command for stdio connections (required when type=stdio)
        args: Arguments for stdio command
        description: Service description for LLM skill selection
        extra_params: Extra parameters passed to the underlying client
        auth_provider: Authentication provider (injected by business layer)

    Example:
        >>> config = MCPConfig(
        ...     name="filesystem",
        ...     type="stdio",
        ...     command="npx",
        ...     args=["-y", "@modelcontextprotocol/server-filesystem", "/workspace"],
        ...     description="File system operations",
        ... )
    """

    model_config = {"arbitrary_types_allowed": True}

    name: str = Field(..., description="MCP server name (unique identifier)")
    type: str = Field(default="", description="Connection type: sse, stdio, streamable_http (auto-inferred if omitted)")
    url: str | None = Field(default=None, description="URL for SSE or HTTP connections")
    command: str | None = Field(default=None, description="Command for stdio connections")

    @model_validator(mode="before")
    @classmethod
    def _infer_type(cls, data: dict[str, object]) -> dict[str, object]:
        """Auto-infer transport type from url/command when type is omitted."""
        if isinstance(data, dict) and not data.get("type"):
            if data.get("command"):
                data["type"] = "stdio"
            elif data.get("url"):
                url = str(data["url"])
                data["type"] = "streamable_http" if "/mcp" in url else "sse"
            else:
                raise ValueError(
                    f"MCPConfig '{data.get('name', '?')}': "
                    "cannot infer 'type' — provide 'type', 'command', or 'url'"
                )
        return data
    args: list[str] | None = Field(default=None, description="Arguments for stdio connections")
    description: str = Field(
        default="",
        description="Service description for LLM skill selection",
    )
    headers: dict[str, str] | None = Field(
        default=None,
        description=(
            "HTTP headers for SSE/streamable_http connections. "
            "Values may contain secret references (e.g. {{secret:KEY_NAME}}) "
            "that the business layer resolves via MCPAuthProvider before connecting."
        ),
    )
    extra_params: dict[str, object] | None = Field(default=None, description="Additional parameters for client")
    required_secrets: list[str] | None = Field(
        default=None,
        description="List of secret keys this MCP server is allowed to access (Scoped Secret Injection)",
    )
    tool_include: list[str] | None = Field(
        default=None,
        description=(
            "Tool whitelist: only these tool names are registered. "
            "None/empty = no whitelist constraint. Takes precedence over tool_exclude."
        ),
    )
    tool_exclude: list[str] | None = Field(
        default=None,
        description=(
            "Tool blacklist: all tools EXCEPT these are registered. "
            "Ignored when tool_include is non-empty. None/empty = no blacklist constraint."
        ),
    )
    connect_timeout: float = Field(
        default=15.0,
        ge=1.0,
        le=600.0,
        description="Connection timeout in seconds (stdio startup may be slow)",
    )
    execute_timeout: float = Field(
        default=120.0,
        ge=1.0,
        le=600.0,
        description="Tool execution timeout in seconds (complex operations like DB queries need more time)",
    )
    max_output_chars: int = Field(
        default=100_000,
        ge=1000,
        le=10_000_000,
        description=(
            "Maximum characters for tool result text before truncation. "
            "Prevents oversized MCP responses from blowing up the LLM context window. "
            "Set to a higher value for servers that legitimately return large payloads."
        ),
    )
    ssl_verify: bool | str | None = Field(
        default=None,
        description=(
            "TLS certificate verification for HTTP/SSE transports. "
            "None or True = default CA verification; False = disable; "
            "str = path to a custom CA bundle — a PEM file or an OpenSSL "
            "capath directory of hashed certs (supports ~ expansion)"
        ),
    )
    client_cert: str | None = Field(
        default=None,
        description=(
            "TLS client certificate path for mTLS (mutual TLS). "
            "PEM file containing the client certificate (supports ~ expansion). "
            "Only applies to sse/streamable_http transports."
        ),
    )
    client_key: str | None = Field(
        default=None,
        description=(
            "TLS client private key path (separate from cert). "
            "Optional — omit if the key is bundled in the client_cert PEM. "
            "Supports ~ expansion."
        ),
    )
    client_key_password: str | None = Field(
        default=None,
        description=(
            "Passphrase for an encrypted client private key. "
            "Stored encrypted at rest by the business layer; never logged. "
            "Required only when the key (separate or bundled in client_cert) is passphrase-protected."
        ),
    )
    auth_provider: MCPAuthProvider | None = Field(
        default=None,
        exclude=True,
        description="Authentication provider for remote connections (business layer injects)",
    )

    @model_validator(mode="after")
    def _validate_transport(self) -> MCPConfig:
        if self.type in ("sse", "streamable_http") and not self.url:
            raise ValueError(f"MCPConfig '{self.name}': type='{self.type}' requires 'url'")
        if self.type == "stdio" and not self.command:
            raise ValueError(f"MCPConfig '{self.name}': type='stdio' requires 'command'")
        if self.client_key and not self.client_cert:
            raise ValueError(
                f"MCPConfig '{self.name}': 'client_key' requires 'client_cert' "
                f"(a private key cannot be used without its certificate)"
            )
        if self.client_key_password and not self.client_cert:
            raise ValueError(
                f"MCPConfig '{self.name}': 'client_key_password' requires 'client_cert' "
                f"(set the client certificate whose key is passphrase-protected)"
            )
        return self


def should_register_mcp_tool(
    tool_name: str,
    tool_include: list[str] | None,
    tool_exclude: list[str] | None,
) -> bool:
    """Decide whether an MCP tool passes the per-server include/exclude filter.

    Single source of truth for MCP tool whitelisting (mirrors the include/exclude
    semantics so direct and PTC-skill paths stay consistent):
    - ``tool_include`` non-empty → only listed tools register (whitelist).
    - else ``tool_exclude`` non-empty → all but listed tools register (blacklist).
    - both empty/None → register all (zero-config default = full registration).
    """
    if tool_include:
        return tool_name in tool_include
    if tool_exclude:
        return tool_name not in tool_exclude
    return True


def sanitize_mcp_name_component(value: str) -> str:
    """Sanitize an MCP name component for safe tool-name generation.

    Replaces any character outside ``[A-Za-z0-9_]`` with ``_``,
    collapses consecutive underscores into one, and strips leading/
    trailing underscores so the ``__`` delimiter in
    ``mcp__{server}__{tool}`` stays unambiguous.  Falls back to
    ``'unnamed'`` when the result would otherwise be empty.
    Generated names satisfy provider validation rules
    (e.g. OpenAI's function-name regex).
    """
    result = re.sub(r"[^A-Za-z0-9_]", "_", str(value or ""))
    result = re.sub(r"_{2,}", "_", result)
    return result.strip("_") or "unnamed"


_MCP_PREFIX = "mcp__"
_MCP_DELIM = "__"


def is_mcp_tool_name(name: str) -> bool:
    """Return True if *name* follows the ``mcp__{server}__{tool}`` convention."""
    return name.startswith(_MCP_PREFIX) and _MCP_DELIM in name[len(_MCP_PREFIX) :]


def parse_mcp_tool_name(name: str) -> tuple[str, str] | None:
    """Parse ``mcp__{server}__{tool}`` into ``(server, tool)``.

    Returns None if *name* does not match the convention.
    The double-underscore delimiter is unambiguous even when server or
    tool names contain single underscores.
    """
    if not name.startswith(_MCP_PREFIX):
        return None
    rest = name[len(_MCP_PREFIX) :]
    idx = rest.find(_MCP_DELIM)
    if idx <= 0:
        return None
    return rest[:idx], rest[idx + len(_MCP_DELIM) :]


__all__ = [
    "MCPAuthProvider",
    "MCPConfig",
    "is_mcp_tool_name",
    "parse_mcp_tool_name",
    "sanitize_mcp_name_component",
    "should_register_mcp_tool",
]
