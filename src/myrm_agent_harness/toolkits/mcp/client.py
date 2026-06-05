"""MCP client manager.

Provides MCP server connection initialization and configuration management:
- Supports SSE, Stdio, and Streamable HTTP transports
- Configuration format conversion
- Multi-server client initialization
- Optional auth integration (via MCPAuthProvider Protocol for HTTP headers)
- TLS/mTLS support via httpx_client_factory injection for HTTP transports

[INPUT]
- langchain_mcp_adapters (POS: MCP client library)

[OUTPUT]
- MCPClientManager: MCP client initialization and config conversion
- MCPServerConfigProtocol: protocol defining required MCP server config attributes

[POS]
MCP client management layer. Handles MCP server connection setup, transport config conversion,
and multi-server client initialization with optional auth and TLS/mTLS injection.
"""

from __future__ import annotations

import logging
import ssl
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Protocol

from langchain_mcp_adapters.client import MultiServerMCPClient

logger = logging.getLogger(__name__)

HttpxClientFactory = Callable[..., object]


def _noninteractive_passphrase() -> bytes:
    """Passphrase callback used when no passphrase is configured.

    Prevents OpenSSL from falling back to an interactive TTY prompt (which would
    hang a headless server) when a client key turns out to be encrypted: the
    empty passphrase fails decryption cleanly, surfacing an actionable error.
    """
    return b""


class MCPServerConfigProtocol(Protocol):
    """Protocol defining required MCP server config attributes.

    Compatible with multiple config types:
    - myrm_agent_harness.toolkits.mcp.MCPConfig (Pydantic BaseModel)
    - app.core.types.MCPServerConfig (Pydantic BaseModel)
    """

    name: str
    type: str
    url: str | None
    command: str | None
    args: list[str] | None
    description: str  # used by LLM to decide when to use this service
    headers: dict[str, str] | None  # HTTP headers for SSE/streamable_http
    extra_params: dict[str, object] | None
    required_secrets: list[str] | None
    tool_include: list[str] | None  # tool whitelist (takes precedence over tool_exclude)
    tool_exclude: list[str] | None  # tool blacklist (ignored when tool_include set)
    connect_timeout: float
    execute_timeout: float
    ssl_verify: bool | str | None  # TLS CA policy for HTTP transports
    client_cert: str | None  # mTLS client certificate path
    client_key: str | None  # mTLS client private key path (optional if bundled)
    client_key_password: str | None  # passphrase for an encrypted client key


class MCPClientManager:
    """MCP client manager."""

    @staticmethod
    def convert_server_config_to_client_format(
        server_config: MCPServerConfigProtocol,
    ) -> dict[str, object]:
        """Convert server config to MultiServerMCPClient format."""
        server_type = server_config.type
        connect_timeout = getattr(server_config, "connect_timeout", 15.0)
        execute_timeout = getattr(server_config, "execute_timeout", 120.0)

        # read_timeout_seconds = execution timeout for MCP tool calls
        client_config: dict[str, object] = {
            "session_kwargs": {"read_timeout_seconds": timedelta(seconds=execute_timeout)}
        }

        if server_type == "sse":
            client_config.update(
                {
                    "url": server_config.url,
                    "transport": "sse",
                    "timeout": connect_timeout,
                    "sse_read_timeout": execute_timeout,
                }
            )
        elif server_type == "streamable_http":
            client_config.update(
                {
                    "url": server_config.url,
                    "transport": "streamable_http",
                    "timeout": connect_timeout,
                    "sse_read_timeout": execute_timeout,
                }
            )
        elif server_type == "stdio":
            client_config.update(
                {
                    "command": server_config.command,
                    "args": server_config.args or [],
                    "transport": "stdio",
                }
            )
        else:
            raise ValueError(f"Unsupported transport type: {server_type}")

        if hasattr(server_config, "extra_params") and server_config.extra_params:
            client_config.update(server_config.extra_params)

        config_headers = getattr(server_config, "headers", None)
        if config_headers and server_type in ("sse", "streamable_http"):
            existing: dict[str, str] = dict(client_config.get("headers") or {})  # type: ignore[arg-type]
            existing.update(config_headers)
            client_config["headers"] = existing  # type: ignore[assignment]

        if server_type in ("sse", "streamable_http"):
            factory = MCPClientManager._build_tls_client_factory(server_config)
            if factory is not None:
                client_config["httpx_client_factory"] = factory

        return client_config

    @staticmethod
    async def initialize_client(
        mcp_config: Sequence[MCPServerConfigProtocol] | None = None,
    ) -> MultiServerMCPClient:
        """Initialize MCP client with given server configurations."""
        if not mcp_config:
            return MultiServerMCPClient({})

        client_config: dict[str, dict[str, object]] = {}
        for server_config in mcp_config:
            try:
                name = server_config.name
                config = MCPClientManager.convert_server_config_to_client_format(server_config)
                await MCPClientManager._inject_auth_headers(server_config, config)
                client_config[name] = config
            except Exception as e:
                logger.error(f"Failed to configure MCP server {server_config.name}: {e!s}")

        if not client_config:
            logger.warning("No valid MCP server configurations found")
            return MultiServerMCPClient({})

        try:
            client = MultiServerMCPClient(client_config)
            logger.info(f"Initialized MCP client with {len(client_config)} servers")
            return client
        except Exception as e:
            logger.error(f"Failed to initialize MCP client: {e!s}")
            return MultiServerMCPClient({})

    @staticmethod
    def _resolve_tls_path(raw_path: str, label: str, server_name: str, *, allow_dir: bool = False) -> str:
        """Expand ~ and validate that the TLS path exists.

        ``allow_dir`` permits an OpenSSL ``capath`` directory for the CA bundle
        (a hashed-cert dir); client cert/key paths must always be regular files.
        """
        expanded = str(Path(raw_path).expanduser())
        path = Path(expanded)
        if path.is_file() or (allow_dir and path.is_dir()):
            return expanded
        kind = "file or directory" if allow_dir else "file"
        raise FileNotFoundError(f"MCP server '{server_name}': {label} {kind} not found: {expanded}")

    @staticmethod
    def _build_ssl_context(
        server_config: MCPServerConfigProtocol,
    ) -> ssl.SSLContext | None:
        """Build an ``ssl.SSLContext`` from the TLS/mTLS config, or None if unset.

        Uses ``SSLContext`` + ``load_cert_chain`` (not httpx's deprecated
        ``cert=``/``verify=<str>`` shortcuts) so encrypted client keys are
        supported and no ``DeprecationWarning`` is emitted. Cross-field
        inconsistencies and key-load failures (bad passphrase, malformed PEM)
        are surfaced as actionable ``ValueError``s instead of being silently
        dropped.
        """
        import httpx

        ssl_verify = server_config.ssl_verify
        client_cert = server_config.client_cert
        client_key = server_config.client_key
        client_key_password = server_config.client_key_password
        name = server_config.name

        if ssl_verify is None and client_cert is None and client_key is None and client_key_password is None:
            return None

        # 1) Base context honoring the CA-verification policy.
        if ssl_verify is False:
            ssl_context = httpx.create_ssl_context(verify=False)
        elif isinstance(ssl_verify, str):
            ca_path = MCPClientManager._resolve_tls_path(ssl_verify, "ssl_verify (CA bundle)", name, allow_dir=True)
            ssl_context = (
                ssl.create_default_context(capath=ca_path)
                if Path(ca_path).is_dir()
                else ssl.create_default_context(cafile=ca_path)
            )
        else:  # None or True → system/certifi default trust store
            ssl_context = httpx.create_ssl_context(verify=True)

        # 2) Cross-field validation (fail loud — never silently drop a key/password).
        if client_cert is None:
            if client_key is not None:
                raise ValueError(
                    f"MCP server '{name}': 'client_key' provided without 'client_cert' "
                    f"(a private key cannot be used without its certificate)"
                )
            if client_key_password is not None:
                raise ValueError(f"MCP server '{name}': 'client_key_password' provided without 'client_cert'")
            return ssl_context

        # 3) Load the client certificate chain (mTLS), supporting encrypted keys.
        cert_path = MCPClientManager._resolve_tls_path(client_cert, "client_cert", name)
        key_path = (
            MCPClientManager._resolve_tls_path(client_key, "client_key", name) if client_key is not None else None
        )
        password = client_key_password if client_key_password is not None else _noninteractive_passphrase
        try:
            ssl_context.load_cert_chain(certfile=cert_path, keyfile=key_path, password=password)
        except (ssl.SSLError, OSError) as exc:
            hint = (
                "verify the client key passphrase (client_key_password)"
                if client_key_password
                else "the key may be passphrase-protected — set client_key_password"
            )
            raise ValueError(f"MCP server '{name}': failed to load client certificate/key: {exc} ({hint})") from exc

        return ssl_context

    @staticmethod
    def _build_tls_client_factory(
        server_config: MCPServerConfigProtocol,
    ) -> HttpxClientFactory | None:
        """Build an httpx_client_factory closure when mTLS or custom SSL is configured.

        Returns None if no TLS customization is needed (default behaviour).
        The SSLContext is built once and shared across clients (thread-safe reuse).
        """
        import httpx

        ssl_context = MCPClientManager._build_ssl_context(server_config)
        if ssl_context is None:
            return None

        def factory(
            headers: dict[str, str] | None = None,
            timeout: httpx.Timeout | None = None,
            auth: httpx.Auth | None = None,
        ) -> httpx.AsyncClient:
            return httpx.AsyncClient(
                headers=headers,
                timeout=timeout,
                auth=auth,
                verify=ssl_context,
                follow_redirects=True,
            )

        logger.info(
            "[MCP TLS] Server '%s': verify=%s, client_cert=%s, key_passphrase=%s",
            server_config.name,
            "disabled"
            if server_config.ssl_verify is False
            else ("custom CA" if isinstance(server_config.ssl_verify, str) else "default"),
            "configured" if server_config.client_cert else "none",
            "yes" if server_config.client_key_password else "no",
        )
        return factory

    @staticmethod
    async def _inject_auth_headers(
        server_config: MCPServerConfigProtocol,
        client_config: dict[str, object],
    ) -> None:
        """Inject authentication headers from MCPAuthProvider into the connection config.

        Only applies to HTTP-based transports (SSE, streamable_http) since stdio
        connections don't use HTTP headers. Auth failures are non-fatal — the
        connection proceeds without auth, and the server rejects if needed.
        """
        auth_provider = getattr(server_config, "auth_provider", None)
        if auth_provider is None:
            return

        transport = client_config.get("transport", "")
        if transport not in ("sse", "streamable_http"):
            return

        try:
            auth_headers = await auth_provider.get_auth_headers(
                server_config.name,
                server_config.url or "",
            )
            if not auth_headers:
                return

            existing_headers: dict[str, str] = dict(client_config.get("headers") or {})  # type: ignore[arg-type]
            existing_headers.update(auth_headers)
            client_config["headers"] = existing_headers  # type: ignore[assignment]
        except Exception:
            logger.warning(
                "Auth provider failed for MCP server '%s', proceeding without auth",
                server_config.name,
                exc_info=True,
            )
