"""MCP client manager.

Provides MCP server connection configuration and ``mcp.client.Client`` target
building:
- Supports SSE, Stdio, and Streamable HTTP transports
- Configuration format conversion (config → ``Client`` target)
- Optional auth integration (via MCPAuthProvider Protocol for HTTP headers)
- TLS/mTLS support via ``ssl.SSLContext`` injection for HTTP transports

[INPUT]
- mcp (POS: MCP SDK 2.x — Client, StdioServerParameters)

[OUTPUT]
- MCPClientManager: MCP client config conversion and target building
- MCPServerConfigProtocol: protocol defining required MCP server config attributes

[POS]
MCP client management layer. Handles MCP server connection config conversion,
Client target building, and optional auth/TLS injection.
"""

from __future__ import annotations

import logging
import ssl
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from mcp import StdioServerParameters

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
    host_serial: bool  # host-level serial scheduling override
    connect_timeout: float
    execute_timeout: float
    keepalive_interval: float | None
    ssl_verify: bool | str | None  # TLS CA policy for HTTP transports
    client_cert: str | None  # mTLS client certificate path
    client_key: str | None  # mTLS client private key path (optional if bundled)
    client_key_password: str | None  # passphrase for an encrypted client key


class MCPClientManager:
    """MCP client manager — builds ``mcp.client.Client`` targets from config."""

    @staticmethod
    def build_client_target(
        server_config: MCPServerConfigProtocol,
    ) -> str | StdioServerParameters:
        """Build a ``mcp.client.Client`` target from server config.

        Returns a URL string for HTTP transports or ``StdioServerParameters``
        for stdio — ``Client`` auto-detects the transport from the target type.
        """
        server_type = server_config.type

        if server_type in ("sse", "streamable_http"):
            url = server_config.url
            if not url:
                raise ValueError(f"MCP server '{server_config.name}': HTTP transport requires 'url'")
            return str(url)

        if server_type == "stdio":
            from mcp import StdioServerParameters

            return StdioServerParameters(
                command=str(server_config.command or ""),
                args=[str(a) for a in (server_config.args or [])],
            )

        raise ValueError(f"Unsupported transport type: {server_type}")

    @staticmethod
    async def prepare_server_configs(
        mcp_config: Sequence[MCPServerConfigProtocol],
    ) -> dict[str, MCPServerConfigProtocol]:
        """Validate configs and inject auth headers; returns name→config mapping.

        Configs that fail validation are logged and skipped.
        """
        result: dict[str, MCPServerConfigProtocol] = {}
        for cfg in mcp_config:
            try:
                MCPClientManager.build_client_target(cfg)
                await MCPClientManager._inject_auth_headers_into_config(cfg)
                result[cfg.name] = cfg
            except Exception as e:
                logger.error("Failed to configure MCP server %s: %s", cfg.name, e)
        if not result:
            logger.warning("No valid MCP server configurations found")
        return result

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

        Uses ``SSLContext`` + ``load_cert_chain`` so encrypted client keys are
        supported. Cross-field inconsistencies and key-load failures (bad
        passphrase, malformed PEM) are surfaced as actionable ``ValueError``s
        instead of being silently dropped.
        """
        import httpx2

        ssl_verify = server_config.ssl_verify
        client_cert = server_config.client_cert
        client_key = server_config.client_key
        client_key_password = server_config.client_key_password
        name = server_config.name

        if ssl_verify is None and client_cert is None and client_key is None and client_key_password is None:
            return None

        if ssl_verify is False:
            ssl_context = httpx2.create_ssl_context(verify=False)
        elif isinstance(ssl_verify, str):
            ca_path = MCPClientManager._resolve_tls_path(ssl_verify, "ssl_verify (CA bundle)", name, allow_dir=True)
            ssl_context = (
                ssl.create_default_context(capath=ca_path)
                if Path(ca_path).is_dir()
                else ssl.create_default_context(cafile=ca_path)
            )
        else:
            ssl_context = httpx2.create_ssl_context(verify=True)

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
        """Build an httpx2 client factory closure for mTLS or custom SSL.

        Returns None if no TLS customization is needed (default behaviour).
        The SSLContext is built once and shared across clients (thread-safe reuse).
        """
        import httpx2

        ssl_context = MCPClientManager._build_ssl_context(server_config)
        if ssl_context is None:
            return None

        def factory(
            headers: dict[str, str] | None = None,
            timeout: httpx2.Timeout | None = None,
            auth: httpx2.Auth | None = None,
        ) -> httpx2.AsyncClient:
            return httpx2.AsyncClient(
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
    def get_headers(server_config: MCPServerConfigProtocol) -> dict[str, str]:
        """Merge static config headers with any injected auth headers.

        Returns the combined header dict for HTTP transports (empty for stdio).
        """
        if server_config.type not in ("sse", "streamable_http"):
            return {}
        headers: dict[str, str] = dict(server_config.headers or {})
        injected = getattr(server_config, "_injected_auth_headers", None)
        if injected:
            headers.update(injected)
        return headers

    @staticmethod
    async def _inject_auth_headers_into_config(
        server_config: MCPServerConfigProtocol,
    ) -> None:
        """Inject authentication headers from MCPAuthProvider into the config object.

        Only applies to HTTP-based transports (SSE, streamable_http) since stdio
        connections don't use HTTP headers. Auth failures are non-fatal — the
        connection proceeds without auth, and the server rejects if needed.
        """
        auth_provider = getattr(server_config, "auth_provider", None)
        if auth_provider is None:
            return

        if server_config.type not in ("sse", "streamable_http"):
            return

        try:
            auth_headers = await auth_provider.get_auth_headers(
                server_config.name,
                server_config.url or "",
            )
            if auth_headers:
                object.__setattr__(server_config, "_injected_auth_headers", auth_headers)
        except Exception:
            logger.warning(
                "Auth provider failed for MCP server '%s', proceeding without auth",
                server_config.name,
                exc_info=True,
            )
