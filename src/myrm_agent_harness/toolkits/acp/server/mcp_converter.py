"""ACP MCP server configuration converter.

Converts host-provided ACP MCP servers into Myrm native MCPConfig instances.

[INPUT]
- acp.schema::HttpMcpServer, McpServerStdio, SseMcpServer (POS: ACP official schema) [optional]
- toolkits.mcp.config::MCPConfig (POS: Myrm native MCP server configuration)

[OUTPUT]
- convert_acp_mcp_servers: Convert ACP MCP servers into a list of MCPConfig

[POS]
Adapter layer bridging ACP protocol MCP server definitions to internal MCPConfig models.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Mapping

from myrm_agent_harness.toolkits.mcp.config import MCPConfig

logger = logging.getLogger(__name__)


def _extract_env_mapping(env_obj: object) -> dict[str, str]:
    """Extract environment variable mapping from various ACP schema representations."""
    if not env_obj:
        return {}
    if isinstance(env_obj, Mapping):
        return {str(k): str(v) for k, v in env_obj.items()}
    if isinstance(env_obj, Sequence):
        env_dict: dict[str, str] = {}
        for item in env_obj:
            if hasattr(item, "name") and hasattr(item, "value"):
                env_dict[str(item.name)] = str(item.value)
            elif isinstance(item, Mapping) and "name" in item and "value" in item:
                env_dict[str(item["name"])] = str(item["value"])
        return env_dict
    return {}


def _extract_headers_mapping(headers_obj: object) -> dict[str, str]:
    """Extract HTTP headers mapping from various ACP schema representations."""
    if not headers_obj:
        return {}
    if isinstance(headers_obj, Mapping):
        return {str(k): str(v) for k, v in headers_obj.items()}
    if isinstance(headers_obj, Sequence):
        headers_dict: dict[str, str] = {}
        for item in headers_obj:
            if hasattr(item, "name") and hasattr(item, "value"):
                headers_dict[str(item.name)] = str(item.value)
            elif isinstance(item, Mapping) and "name" in item and "value" in item:
                headers_dict[str(item["name"])] = str(item["value"])
        return headers_dict
    return {}


def convert_acp_mcp_servers(
    host_mcp_servers: Sequence[object] | None,
) -> list[MCPConfig]:
    """Convert a sequence of ACP host MCP server descriptors into Myrm MCPConfigs.

    Supports stdio, SSE, and HTTP transport descriptors. Silently skips invalid entries
    while logging warnings.
    """
    if not host_mcp_servers:
        return []

    configs: list[MCPConfig] = []
    for item in host_mcp_servers:
        if isinstance(item, MCPConfig):
            configs.append(item)
            continue

        try:
            name = getattr(item, "name", None)
            if not name and isinstance(item, Mapping):
                name = item.get("name")
            if not name:
                logger.warning("acp_mcp_convert_skipped_unnamed item=%r", item)
                continue
            server_name = str(name)

            command = getattr(item, "command", None)
            if command is None and isinstance(item, Mapping):
                command = item.get("command")

            if command is not None:
                args_raw = getattr(item, "args", None)
                if args_raw is None and isinstance(item, Mapping):
                    args_raw = item.get("args")
                args_list = [str(a) for a in args_raw] if isinstance(args_raw, Sequence) else []

                env_raw = getattr(item, "env", None)
                if env_raw is None and isinstance(item, Mapping):
                    env_raw = item.get("env")
                env_map = _extract_env_mapping(env_raw)

                extra_params: dict[str, object] | None = {"env": env_map} if env_map else None
                configs.append(
                    MCPConfig(
                        name=server_name,
                        type="stdio",
                        command=str(command),
                        args=args_list,
                        extra_params=extra_params,
                    )
                )
                continue

            url = getattr(item, "url", None)
            if url is None and isinstance(item, Mapping):
                url = item.get("url")

            if url is not None:
                headers_raw = getattr(item, "headers", None)
                if headers_raw is None and isinstance(item, Mapping):
                    headers_raw = item.get("headers")
                headers_map = _extract_headers_mapping(headers_raw)

                url_str = str(url)
                inferred_type = "streamable_http" if "/mcp" in url_str else "sse"
                configs.append(
                    MCPConfig(
                        name=server_name,
                        type=inferred_type,
                        url=url_str,
                        headers=headers_map or None,
                    )
                )
                continue

            logger.warning("acp_mcp_convert_unsupported_type item=%r", item)

        except Exception as exc:
            logger.warning("acp_mcp_convert_failed item=%r error=%s", item, exc)

    return configs
