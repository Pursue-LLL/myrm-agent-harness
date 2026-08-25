"""MCP (Model Context Protocol) module.

Provides MCP client integration with:
- SSE, Stdio, Streamable HTTP transports
- Parallel multi-server tool fetching
- User-friendly configuration interface
- Connection pool management
- URL SSRF protection and response validation (security submodule)


[INPUT]
- agent::MCPAgent (POS: MCP agent layer)
- client::MCPClientManager, MCPServerConfigProtocol (POS: MCP client management layer)
- config::MCPConfig (POS: MCP user-facing configuration)
- connection_manager::MCPConnectionManager, get_mcp_connection, get_mcp_connection_manager (POS: MCP connection pool layer)
- security (POS: MCP security — URL SSRF protection and response validation)
- schema (POS: MCP inbound tool schema normalization — canonicalization, $ref inlining, composite flattening, argument coercion)

[OUTPUT]
- MCPAgent, MCPClientManager, MCPConfig, MCPConnectionManager, MCPServerConfigProtocol: core MCP types
- OversizedResultHandler: callback type for vault-spilling oversized MCP tool outputs
- get_schema_coercion_stats/reset_schema_coercion_stats: runtime counters for MCP schema coercion observability
- MCPResponseError, MCPResponseValidator, MCPURLValidator, ResolvedURL, URLValidationError: security types
- get_mcp_connection, get_mcp_connection_manager: connection pool accessors

[POS]
MCP toolkit entry point. Aggregates client management, agent tool fetching, connection pooling,
configuration, and security validation for unified MCP protocol support.
"""

from .agent import MCPAgent
from .client import MCPClientManager, MCPServerConfigProtocol
from .config import MCPConfig
from .connection_manager import (
    MCPConnectionManager,
    get_mcp_connection,
    get_mcp_connection_manager,
)
from .env_guard import is_dangerous_env_key, sanitize_mcp_env
from .oauth import (
    MCPOAuthConfig,
    MCPOAuthProvider,
    MCPOAuthToken,
    MCPOAuthTokenStore,
    build_authorization_url,
    generate_pkce_pair,
)
from .placeholders import expand_placeholders, resolve_stdio_launch
from .result_processing import OversizedResultHandler
from .schema import get_schema_coercion_stats, reset_schema_coercion_stats
from .security import (
    MCPResponseError,
    MCPResponseValidator,
    MCPURLValidator,
    ResolvedURL,
    URLValidationError,
)
from .structured_tool import SafeStructuredTool

__all__ = [
    "MCPAgent",
    "MCPClientManager",
    "MCPConfig",
    "MCPConnectionManager",
    "MCPOAuthConfig",
    "MCPOAuthProvider",
    "MCPOAuthToken",
    "MCPOAuthTokenStore",
    "MCPResponseError",
    "MCPResponseValidator",
    "MCPServerConfigProtocol",
    "MCPURLValidator",
    "OversizedResultHandler",
    "ResolvedURL",
    "SafeStructuredTool",
    "URLValidationError",
    "build_authorization_url",
    "expand_placeholders",
    "generate_pkce_pair",
    "get_mcp_connection",
    "get_mcp_connection_manager",
    "get_schema_coercion_stats",
    "is_dangerous_env_key",
    "reset_schema_coercion_stats",
    "resolve_stdio_launch",
    "sanitize_mcp_env",
]
