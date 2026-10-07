"""Generates plug-and-play MCP configuration snippets for external AI tools.

[INPUT]
- toolkits.memory.universal_mcp_bridge.types::ClientConfigSnippet, ExternalClientKind, McpTransportKind,
  UniversalMemoryBridgeOptions (POS: Typed data contracts for the universal mcp bridge subsystem.)

[OUTPUT]
- ExternalClientConfigGenerator: Generates plug-and-play MCP configuration snippets for external AI tools.

[POS]
Generates plug-and-play MCP configuration snippets for external AI tools.
"""

import json
from pathlib import Path

from .types import (
    ClientConfigSnippet,
    ExternalClientKind,
    McpTransportKind,
    UniversalMemoryBridgeOptions,
)


class ExternalClientConfigGenerator:
    """Generates plug-and-play MCP configuration snippets for external AI tools."""

    @classmethod
    def generate(
        cls,
        client_kind: ExternalClientKind,
        options: UniversalMemoryBridgeOptions | None = None,
    ) -> ClientConfigSnippet:
        """Generate standardized configuration snippet for target external client."""
        opts = options or UniversalMemoryBridgeOptions()

        if client_kind == ExternalClientKind.CLAUDE_CODE:
            return cls._generate_claude_code(opts)
        elif client_kind == ExternalClientKind.CURSOR:
            return cls._generate_cursor(opts)
        elif client_kind == ExternalClientKind.VSCODE_CLINE:
            return cls._generate_vscode_cline(opts)
        elif client_kind == ExternalClientKind.CODEBUDDY:
            return cls._generate_codebuddy(opts)
        elif client_kind == ExternalClientKind.HERMES:
            return cls._generate_hermes(opts)
        else:
            msg = f"Unsupported external client kind: {client_kind}"
            raise ValueError(msg)

    @classmethod
    def generate_all(
        cls,
        options: UniversalMemoryBridgeOptions | None = None,
    ) -> list[ClientConfigSnippet]:
        """Generate configuration snippets for all supported external AI clients."""
        opts = options or UniversalMemoryBridgeOptions()
        return [cls.generate(k, opts) for k in ExternalClientKind]

    @classmethod
    def _generate_claude_code(cls, opts: UniversalMemoryBridgeOptions) -> ClientConfigSnippet:
        server_config: dict[str, object] = cls._build_server_payload(opts)
        config_payload: dict[str, object] = {
            "mcpServers": {
                "myrm-memory": server_config,
            }
        }
        raw_json = json.dumps(config_payload, indent=2, ensure_ascii=False)
        target_path = str(Path.home() / ".claude.json")

        return ClientConfigSnippet(
            client_kind=ExternalClientKind.CLAUDE_CODE,
            transport=opts.transport,
            target_config_file_path=target_path,
            config_format="json",
            config_payload=config_payload,
            raw_content=raw_json,
            instructions="Copy this snippet into your ~/.claude.json file under 'mcpServers'. Claude Code will automatically connect to Myrm memory hub.",
        )

    @classmethod
    def _generate_cursor(cls, opts: UniversalMemoryBridgeOptions) -> ClientConfigSnippet:
        server_config: dict[str, object] = cls._build_server_payload(opts)
        config_payload: dict[str, object] = {
            "mcpServers": {
                "myrm-memory": server_config,
            }
        }
        raw_json = json.dumps(config_payload, indent=2, ensure_ascii=False)
        target_path = ".cursor/mcp.json"

        return ClientConfigSnippet(
            client_kind=ExternalClientKind.CURSOR,
            transport=opts.transport,
            target_config_file_path=target_path,
            config_format="json",
            config_payload=config_payload,
            raw_content=raw_json,
            instructions="Save as .cursor/mcp.json in your workspace root, or add to Cursor MCP settings.",
        )

    @classmethod
    def _generate_vscode_cline(cls, opts: UniversalMemoryBridgeOptions) -> ClientConfigSnippet:
        server_config: dict[str, object] = cls._build_server_payload(opts)
        config_payload: dict[str, object] = {
            "mcpServers": {
                "myrm-memory": server_config,
            }
        }
        raw_json = json.dumps(config_payload, indent=2, ensure_ascii=False)
        target_path = str(Path.home() / "Library/Application Support/Code/User/globalStorage/saoudrizwan.claude-dev/settings/cline_mcp_settings.json")

        return ClientConfigSnippet(
            client_kind=ExternalClientKind.VSCODE_CLINE,
            transport=opts.transport,
            target_config_file_path=target_path,
            config_format="json",
            config_payload=config_payload,
            raw_content=raw_json,
            instructions="Paste into Cline MCP settings file or open Cline -> MCP Servers -> Add Server.",
        )

    @classmethod
    def _generate_codebuddy(cls, opts: UniversalMemoryBridgeOptions) -> ClientConfigSnippet:
        server_config: dict[str, object] = cls._build_server_payload(opts)
        config_payload: dict[str, object] = {
            "mcpServers": {
                "myrm-memory": server_config,
            }
        }
        raw_json = json.dumps(config_payload, indent=2, ensure_ascii=False)
        target_path = str(Path.home() / ".codebuddy" / ".mcp.json")

        return ClientConfigSnippet(
            client_kind=ExternalClientKind.CODEBUDDY,
            transport=opts.transport,
            target_config_file_path=target_path,
            config_format="json",
            config_payload=config_payload,
            raw_content=raw_json,
            instructions="Paste into ~/.codebuddy/.mcp.json under 'mcpServers'. CodeBuddy will share memory with Myrm.",
        )

    @classmethod
    def _generate_hermes(cls, opts: UniversalMemoryBridgeOptions) -> ClientConfigSnippet:
        target_path = str(Path.home() / ".hermes" / "config.yaml")

        if opts.transport == McpTransportKind.STDIO:
            args_list = [*opts.server_module_args, "--user-id", opts.user_id]
            raw_yaml_lines = [
                "mcp:",
                "  servers:",
                "    myrm_memory:",
                f"      command: {opts.server_binary_path}",
                "      args:",
            ]
            for arg in args_list:
                raw_yaml_lines.append(f"        - {arg}")
            raw_yaml = "\n".join(raw_yaml_lines) + "\n"

            payload: dict[str, object] = {
                "mcp": {
                    "servers": {
                        "myrm_memory": {
                            "command": opts.server_binary_path,
                            "args": args_list,
                        }
                    }
                }
            }
        else:
            url = f"http://{opts.host}:{opts.port}/api/memory/mcp/sse?user_id={opts.user_id}"
            raw_yaml = f"mcp:\n  servers:\n    myrm_memory:\n      url: {url}\n"
            payload = {
                "mcp": {
                    "servers": {
                        "myrm_memory": {
                            "url": url,
                        }
                    }
                }
            }

        return ClientConfigSnippet(
            client_kind=ExternalClientKind.HERMES,
            transport=opts.transport,
            target_config_file_path=target_path,
            config_format="yaml",
            config_payload=payload,
            raw_content=raw_yaml,
            instructions="Append snippet into ~/.hermes/config.yaml under 'mcp.servers'. Hermes will instantly access Myrm memory.",
        )

    @classmethod
    def _build_server_payload(cls, opts: UniversalMemoryBridgeOptions) -> dict[str, object]:
        if opts.transport == McpTransportKind.STDIO:
            args = [*opts.server_module_args, "--user-id", opts.user_id]
            payload: dict[str, object] = {
                "command": opts.server_binary_path,
                "args": args,
            }
            if opts.custom_env:
                payload["env"] = dict(opts.custom_env)
            return payload
        else:
            url = f"http://{opts.host}:{opts.port}/api/memory/mcp/sse?user_id={opts.user_id}"
            return {"url": url}
