"""Agent Plugins 1.0.0 mcp.json parsing (§7.2).

Each server is validated **independently** so a single invalid variant never
prevents loading other servers or components (§7.2.2). ``mcp.json`` itself only
disables MCP for the plugin when its top-level shape, ``$schema``, or version
mismatch with ``plugin.json`` fails; it never invalidates the plugin's skills.

The parser emits normalized ``PluginMcpServer`` records (see models.py). Values
are structured for the business layer to persist into the global ``mcpServers``
config with ``enabled: false`` (the default in ``mcp_migration_item_to_config_dict``).

[INPUT]
-- .models::PluginMcpServer (POS: shared parser output dataclasses)

[OUTPUT]
-- decode_mcp_json / parse_mcp_servers / validate_mcp_top_level: per-server
   variant validation → normalized PluginMcpServer records.

[POS]
Per-server mcp.json variant parser for the framework-level plugin parser.
"""

from __future__ import annotations

import ipaddress
import json
import re
from typing import Any
from urllib.parse import urlsplit

from .manifest import MCP_SCHEMA, schema_version
from .models import PluginMcpServer

# Placeholders recognized in stdio args/env/cwd (§9.2). Expansion is a single,
# non-recursive textual replacement performed by the launching client, not here.
_PLACEHOLDER_RE = re.compile(r"\$\{(PLUGIN_ROOT|PLUGIN_DATA)\}")

# §4.1 + §7.2.1: cwd must be `./`, `${PLUGIN_ROOT}`, or `${PLUGIN_DATA}` rooted.
_CWD_FORM_RE = re.compile(r"^(?:\./|\$\{PLUGIN_ROOT\}(?:/|$)|\$\{PLUGIN_DATA\}(?:/|$))")

# Bare executable token: no path separators, no whitespace, no leading "-".
_BARE_COMMAND_RE = re.compile(r"^[A-Za-z0-9_.+~-]+$")


class McpConfigError(ValueError):
    """Fatal mcp.json error that disables MCP for the plugin (§7.2.2 item 2)."""

    def __init__(self, message: str, code: str = "mcp_invalid_config") -> None:
        super().__init__(message)
        self.code = code


def decode_mcp_json(raw: bytes | None) -> dict[str, Any] | None:
    """Decode mcp.json bytes into its top-level dict.

    Returns ``None`` when absent or not a JSON object. Raises ``McpConfigError``
    for type/shape failures.
    """
    if raw is None:
        return None
    text = raw.decode("utf-8", errors="replace")
    if text.startswith("\ufeff"):
        text = text[1:]
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise McpConfigError(
            f"mcp.json is not valid JSON: {exc}", code="mcp_invalid_json"
        ) from exc
    if not isinstance(decoded, dict):
        raise McpConfigError(
            "mcp.json must be a top-level JSON object", code="mcp_invalid_root"
        )
    return decoded


def validate_mcp_top_level(raw: dict[str, Any], plugin_schema: str | None) -> None:
    """Validate the closed top-level mcp.json shape (§7.2.1, §7.2.2 item 2).

    Args:
        raw: Decoded mcp.json top-level dict.
        plugin_schema: The plugin.json ``$schema`` URI (used to verify the MCP
            config targets the same Agent Plugins version, §10.1).

    Raises: McpConfigError (disables MCP for the plugin).
    """
    schema = raw.get("$schema")
    if not isinstance(schema, str) or schema != MCP_SCHEMA:
        raise McpConfigError(
            f"mcp.json declares unsupported $schema: {schema!r}",
            code="mcp_unsupported_schema",
        )
    if plugin_schema is not None and schema_version(schema) != schema_version(
        plugin_schema
    ):
        raise McpConfigError(
            "mcp.json targets a different Agent Plugins version than plugin.json",
            code="mcp_version_mismatch",
        )
    unknown = set(raw.keys()) - {"$schema", "mcpServers"}
    if unknown:
        raise McpConfigError(
            f"mcp.json contains unknown top-level fields: {sorted(unknown)}",
            code="mcp_unknown_field",
        )
    servers = raw.get("mcpServers")
    if not isinstance(servers, dict):
        raise McpConfigError(
            "mcp.json 'mcpServers' must be an object", code="mcp_invalid_servers"
        )


def parse_mcp_servers(raw: dict[str, Any]) -> list[PluginMcpServer]:
    """Parse each server entry independently, skipping invalid variants.

    Returns only successfully-parsed servers. The caller records per-server
    diagnostics for the failures.
    """
    servers_raw = raw.get("mcpServers")
    if not isinstance(servers_raw, dict):
        return []

    servers: list[PluginMcpServer] = []
    for name, entry in servers_raw.items():
        if not isinstance(entry, dict):
            continue
        parsed = _parse_server(str(name), entry)
        if parsed is not None:
            servers.append(parsed)
    return servers


def _parse_server(name: str, entry: dict[str, Any]) -> PluginMcpServer | None:
    server_type = entry.get("type")
    if server_type == "stdio":
        return _parse_stdio(name, entry)
    if server_type in ("streamable-http", "sse"):
        return _parse_remote(name, entry, is_sse=server_type == "sse")
    # Unknown type or unknown fields → invalid variant (skipped, keep others).
    return None


def _parse_stdio(name: str, entry: dict[str, Any]) -> PluginMcpServer | None:
    command = entry.get("command")
    if not isinstance(command, str) or not command.strip():
        return None
    command = command.strip()

    if not _is_valid_command(command):
        return None

    args = _str_list(entry.get("args"))
    if args is None and "args" in entry:
        return None  # wrong type is an invalid variant

    env = entry.get("env")
    if env is not None:
        if not isinstance(env, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in env.items()
        ):
            return None
        if "PLUGIN_ROOT" in env or "PLUGIN_DATA" in env:
            return None  # reserved env names are prohibited (§9.1)

    cwd = entry.get("cwd")
    if (
        cwd is not None
        and (
            not isinstance(cwd, str)
            or not _CWD_FORM_RE.match(cwd)
            or _contains_escape(cwd)
        )
    ):
        return None

    unknown = set(entry.keys()) - {"type", "command", "args", "env", "cwd"}
    if unknown:
        return None  # unknown field makes the variant invalid (§7.2.1)

    env_key_names = [str(k) for k in env] if isinstance(env, dict) else []
    raw_env = {str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {}

    return PluginMcpServer(
        name=name,
        server_type="stdio",
        command=command,
        args=args,
        url=None,
        headers=None,
        cwd=cwd,
        env_key_names=env_key_names,
        raw_env=raw_env,
    )


def _is_valid_command(command: str) -> bool:
    """Validate a stdio ``command`` (§7.2.1).

    Must be a single executable token: either a bare executable name or a
    plugin-relative path beginning with ``./`` that stays within the plugin root.
    Shell command strings and placeholder expansion are not permitted here.
    """
    if command.startswith("./"):
        return not _contains_escape(command)
    if "$" in command or " " in command or "\t" in command:
        return False
    if command.startswith("/") or command.startswith("\\"):
        return False
    return bool(_BARE_COMMAND_RE.match(command))


def _parse_remote(
    name: str, entry: dict[str, Any], *, is_sse: bool
) -> PluginMcpServer | None:
    url = entry.get("url")
    if not isinstance(url, str) or not url.strip():
        return None
    url = url.strip()
    if not _is_valid_remote_url(url):
        return None

    headers = entry.get("headers")
    if headers is not None:
        if not isinstance(headers, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in headers.items()
        ):
            return None
        # Header names are case-insensitive; an entry with a duplicate name under
        # different casing is invalid (§7.2.1).
        lowered: set[str] = set()
        for header_name in headers:
            lname = header_name.lower()
            if lname in lowered:
                return None
            lowered.add(lname)

    unknown = set(entry.keys()) - {"type", "url", "headers"}
    if unknown:
        return None

    return PluginMcpServer(
        name=name,
        server_type="sse" if is_sse else "streamable_http",
        command=None,
        args=None,
        url=url,
        headers=(
            {str(k): str(v) for k, v in headers.items()}
            if isinstance(headers, dict)
            else None
        ),
        cwd=None,
    )


def _is_valid_remote_url(url: str) -> bool:
    """Validate a remote MCP URL (§7.2.1).

    Must be an absolute HTTP/HTTPS URL without user information or a fragment.
    Non-loopback endpoints MUST use HTTPS; HTTP is only allowed for localhost or
    loopback IP literals.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return False
    if parts.fragment or parts.username or parts.password:
        return False
    return _is_loopback_host(parts.hostname or "") or parts.scheme == "https"


def _is_loopback_host(hostname: str) -> bool:
    lower = hostname.lower()
    if lower == "localhost":
        return True
    try:
        return ipaddress.ip_address(lower).is_loopback
    except ValueError:
        return False


def _str_list(value: object) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return list(value)
    return None


def _contains_escape(path: str) -> bool:
    """Reject path traversal and absolute escapes in plugin-relative paths."""
    if path.startswith("/") or path.startswith("\\") or re.match(r"^[A-Za-z]:\\", path):
        return True
    return ".." in path.split("/") or ".." in path.split("\\")


def has_placeholders(*values: str | None) -> bool:
    """Return True if any value references a PLUGIN_ROOT/PLUGIN_DATA placeholder.

    Presence of placeholders lets the business layer keep key/placeholder pairs
    and defer expansion to the launching client, but it is not a parse error.
    """
    return any(value is not None and _PLACEHOLDER_RE.search(value) for value in values)
