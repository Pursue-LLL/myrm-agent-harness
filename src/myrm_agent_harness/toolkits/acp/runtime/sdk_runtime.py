"""SDK runtime backend — direct integration with Claude Agent SDK.

Uses the ``@anthropic-ai/claude-agent-sdk`` Node.js package via subprocess
to invoke ``query()`` API calls. This is an optional backend that requires
the SDK to be installed.

This module is intentionally kept as a thin adapter. The SDK handles its own
session management, tool execution, and permission callbacks internally.

[INPUT]
- toolkits.acp.types::AcpError, AcpErrorCode, BackendCapabilities (POS: ACP runtime type definitions layer. Provides all ACP-related core abstractions and data structures, serving as the foundation for the entire ACP module.)
- toolkits.code_execution.utils.workspace_path::WorkspacePathResolver (POS: Workspace path resolver with intelligent auto-detection.)

[OUTPUT]
- SdkRuntime: RuntimeBackend using the Claude Agent SDK via a Node.js b...

[POS]
SDK runtime backend — direct integration with Claude Agent SDK.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator

from myrm_agent_harness.toolkits.acp.runtime._base import BaseRuntime, build_safe_env
from myrm_agent_harness.toolkits.acp.runtime._parser import (
    parse_error,
    parse_json_line,
    parse_thinking,
    parse_tool_result,
    parse_tool_use,
    parse_usage,
)
from myrm_agent_harness.toolkits.acp.types import (
    AcpError,
    AcpErrorCode,
    BackendCapabilities,
    BackendStatus,
    McpServerConfig,
    RuntimeConfig,
    RuntimeEvent,
    RuntimeEventType,
    create_event,
)

logger = logging.getLogger(__name__)


class SdkRuntime(BaseRuntime):
    """RuntimeBackend using the Claude Agent SDK via a Node.js bridge process.

    The SDK is invoked through a small Node.js script that wraps the
    ``query()`` API and streams NDJSON events to stdout. This avoids
    direct FFI complexity while providing full SDK capabilities.

    Requires: ``@anthropic-ai/claude-agent-sdk`` installed in the project
    or globally via npm.
    """

    def __init__(self, runtime_name: str, config: RuntimeConfig) -> None:
        super().__init__(runtime_name, config, backend_type="sdk")
        self._process: asyncio.subprocess.Process | None = None

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            supports_resume=True,
            supports_mcp=True,
            supports_streaming=True,
            supports_tools=True,
        )

    @property
    def is_alive(self) -> bool:
        if self._process is None:
            return False
        return self._process.returncode is None

    async def _do_run_turn(
        self,
        prompt: str,
        session_id: str,
        *,
        mcp_servers: list[McpServerConfig] | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """Execute a turn via the SDK bridge.

        The bridge script receives a JSON payload on stdin and streams
        NDJSON events on stdout.
        """
        yield create_event(
            RuntimeEventType.STATUS_UPDATE,
            session_id,
            status="starting",
            message="Initializing SDK runtime",
        )

        from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import WorkspacePathResolver

        safe_env = build_safe_env(self._config)
        cwd = self._config.cwd or str(WorkspacePathResolver.resolve_workspace_root())

        sdk_input = {
            "prompt": prompt,
            "session_id": session_id,
            "cwd": cwd,
            "permission_mode": self._config.permission_mode,
        }

        if mcp_servers:
            sdk_input["mcp_servers"] = [{"name": s.name, "command": s.command, "args": s.args} for s in mcp_servers]

        command = self._config.command or "claude"
        args = [command, *self._config.args]

        self._process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=safe_env,
            cwd=cwd,
        )
        self._alive = True

        if self._process.stdin is not None:
            payload = json.dumps(sdk_input).encode("utf-8")
            self._process.stdin.write(payload)
            self._process.stdin.write(b"\n")
            await self._process.stdin.drain()
            self._process.stdin.close()

        has_text = False

        if self._process.stdout is not None:
            async for line_bytes in self._process.stdout:
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                event = self._parse_sdk_event(line, session_id)
                if event is not None:
                    if event.type == RuntimeEventType.TEXT_DELTA:
                        has_text = True
                    yield event

        return_code = await self._process.wait()
        self._alive = False

        if return_code != 0 and not has_text:
            stderr_text = ""
            if self._process.stderr is not None:
                stderr_bytes = await self._process.stderr.read()
                stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()

            yield create_event(
                RuntimeEventType.ERROR,
                session_id,
                error=AcpError(
                    code=AcpErrorCode.PROCESS_CRASHED,
                    message=f"SDK process exited with code {return_code}: {stderr_text[:500]}",
                    retryable=True,
                ),
            )
            return

        yield create_event(RuntimeEventType.DONE, session_id, stop_reason="end_turn")

    async def _do_cancel(self, session_id: str) -> None:
        if self._process is not None and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except TimeoutError:
                self._process.kill()

    async def _do_close(self) -> None:
        await self._do_cancel("")
        self._process = None

    async def _do_get_status(self) -> BackendStatus:
        if self._process is None:
            return "stopped"
        if self._process.returncode is None:
            return "ready"
        return "error" if self._process.returncode != 0 else "stopped"

    @staticmethod
    def _parse_sdk_event(line: str, session_id: str) -> RuntimeEvent | None:
        """Parse a single NDJSON line from the SDK bridge output."""
        data = parse_json_line(line)
        if data is None:
            return create_event(RuntimeEventType.TEXT_DELTA, session_id, content=line + "\n")

        event_type = data.get("type", "")

        if event_type in ("text", "assistant", "content_block_delta"):
            content = data.get("text", data.get("content", ""))
            if isinstance(content, str) and content:
                return create_event(RuntimeEventType.TEXT_DELTA, session_id, content=content)

        if event_type == "thinking":
            return parse_thinking(data, session_id)

        if event_type == "tool_use":
            return parse_tool_use(data, session_id)

        if event_type == "tool_result":
            return parse_tool_result(data, session_id)

        if event_type == "usage":
            return parse_usage(data, session_id)

        if event_type == "error":
            return parse_error(data, session_id)

        return None
