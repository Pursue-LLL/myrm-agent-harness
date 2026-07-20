"""CLI runtime backend — spawns a CLI agent process and parses NDJSON output.

Supports Claude CLI (``claude --output-format stream-json``), Codex CLI,
Gemini CLI, and any CLI tool that outputs newline-delimited JSON events.

[INPUT]
- toolkits.acp.types::AcpError, AcpErrorCode, BackendCapabilities (POS: ACP runtime type definitions layer. Provides all ACP-related core abstractions and data structures, serving as the foundation for the entire ACP module.)
- toolkits.code_execution.utils.workspace_path::WorkspacePathResolver (POS: Workspace path resolver with intelligent auto-detection.)

[OUTPUT]
- CliRuntime: RuntimeBackend that spawns a CLI process and parses NDJSO...

[POS]
CLI runtime backend — spawns a CLI agent process and parses NDJSON output.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import AsyncIterator

from myrm_agent_harness.toolkits.acp.runtime._base import BaseRuntime, build_safe_env
from myrm_agent_harness.toolkits.acp.runtime._parser import (
    extract_text_from_event,
    parse_codex_item_event,
    parse_error,
    parse_json_line,
    parse_thinking,
    parse_tool_result,
    parse_tool_use,
    parse_usage,
    unwrap_codex_envelope,
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


_RESUME_COMMANDS = frozenset({"claude"})


def _supports_resume(command: str) -> bool:
    """Check if a CLI command supports the ``--resume`` flag."""
    base = os.path.basename(command)
    return base in _RESUME_COMMANDS


class CliRuntime(BaseRuntime):
    """RuntimeBackend that spawns a CLI process and parses NDJSON output.

    The CLI process receives the prompt via stdin (or as a trailing argument)
    and emits newline-delimited JSON events to stdout. Each JSON line is parsed
    and converted into a RuntimeEvent.

    For CLI tools that support session resume (e.g. Claude CLI ``--resume``),
    the runtime captures the session ID from ``result`` events and injects
    ``--resume <id>`` on subsequent calls to the same session.
    """

    def __init__(self, runtime_name: str, config: RuntimeConfig) -> None:
        super().__init__(runtime_name, config, backend_type="cli")
        self._process: asyncio.subprocess.Process | None = None
        self._cli_session_ids: dict[str, str] = {}

    @property
    def capabilities(self) -> BackendCapabilities:
        can_resume = self._config.command is not None and _supports_resume(self._config.command)
        return BackendCapabilities(
            supports_resume=can_resume,
            supports_mcp=False,
            supports_streaming=True,
            supports_tools=False,
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
        command = self._config.command
        if command is None:
            msg = "CliRuntime requires 'command' in RuntimeConfig"
            raise ValueError(msg)

        yield create_event(
            RuntimeEventType.STATUS_UPDATE,
            session_id,
            status="starting",
            message=f"Spawning CLI process: {command}",
        )

        from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import WorkspacePathResolver

        safe_env = build_safe_env(self._config)
        cwd = self._config.cwd or str(WorkspacePathResolver.resolve_workspace_root())

        args = [command, *self._config.args]

        if "--output-format" in args and "stream-json" in args and "--verbose" not in args:
            args.append("--verbose")

        cli_session = self._cli_session_ids.get(session_id)
        if cli_session and _supports_resume(command) and "--resume" not in args:
            args.extend(["--resume", cli_session])
            logger.info("cli_resume name=%s session=%s cli_session=%s", self._name, session_id, cli_session)

        if self._config.max_turns > 0 and _supports_max_turns(command):
            args.extend(["--max-turns", str(self._config.max_turns)])

        uses_stdin = any(arg == "-p" for arg in self._config.args)
        if not uses_stdin:
            args.append(prompt)

        from myrm_agent_harness.utils.os_compat import get_process_group_kwargs

        self._process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE if uses_stdin else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=safe_env,
            cwd=cwd,
            **get_process_group_kwargs(),
        )
        self._alive = True

        if uses_stdin and self._process.stdin is not None:
            self._process.stdin.write(prompt.encode("utf-8"))
            self._process.stdin.write(b"\n")
            await self._process.stdin.drain()
            self._process.stdin.close()
            await self._process.stdin.wait_closed()

        has_text = False
        stderr_chunks: list[bytes] = []

        async def _drain_stderr() -> None:
            if self._process is not None and self._process.stderr is not None:
                stderr_chunks.append(await self._process.stderr.read())

        stderr_task = asyncio.create_task(_drain_stderr())

        if self._process.stdout is not None:
            async for line_bytes in self._process.stdout:
                line = line_bytes.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                self._capture_cli_session_id(line, session_id)
                event = self._parse_ndjson_line(line, session_id)
                if event is not None:
                    if event.type == RuntimeEventType.TEXT_DELTA:
                        has_text = True
                    yield event

        await stderr_task
        proc = self._process
        if proc is None:
            self._alive = False
            return
        return_code = await proc.wait()
        self._alive = False

        if return_code != 0:
            stderr_text = b"".join(stderr_chunks).decode("utf-8", errors="replace").strip()

            if has_text:
                logger.warning(
                    "cli_process_exited_nonzero name=%s code=%d stderr=%s",
                    self._name,
                    return_code,
                    stderr_text[:200],
                )
            else:
                from myrm_agent_harness.toolkits.acp.runtime._spawn_hints import format_cli_spawn_failure_message

                message = format_cli_spawn_failure_message(
                    command,
                    return_code=return_code,
                    stderr=stderr_text,
                )
                yield create_event(
                    RuntimeEventType.ERROR,
                    session_id,
                    error=AcpError(
                        code=AcpErrorCode.PROCESS_CRASHED,
                        message=message,
                        retryable=True,
                    ),
                )
                return

        yield create_event(
            RuntimeEventType.DONE,
            session_id,
            stop_reason="end_turn",
        )

    async def _do_cancel(self, session_id: str) -> None:
        if self._process is None or self._process.returncode is not None:
            return
        pid = self._process.pid
        from myrm_agent_harness.utils.os_compat import kill_process_group

        try:
            if pid is not None:
                kill_process_group(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        try:
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
        except TimeoutError:
            try:
                if pid is not None:
                    kill_process_group(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    async def _do_resume(self, session_id: str) -> bool:
        return session_id in self._cli_session_ids

    async def _do_close(self) -> None:
        await self._do_cancel("")
        self._process = None
        self._cli_session_ids.clear()

    async def _do_get_status(self) -> BackendStatus:
        if self._process is None:
            return "stopped"
        if self._process.returncode is None:
            return "ready"
        return "error" if self._process.returncode != 0 else "stopped"

    def _capture_cli_session_id(self, line: str, session_id: str) -> None:
        """Extract and cache the CLI-native session ID from result events.

        Claude CLI emits ``{"type": "result", "session_id": "..."}`` at the
        end of each turn. We capture this so subsequent calls with the same
        ``session_id`` can use ``--resume`` for context continuity.
        """
        data = parse_json_line(line)
        if data is None:
            return
        if data.get("type") == "result":
            cli_sid = data.get("session_id")
            if isinstance(cli_sid, str) and cli_sid:
                self._cli_session_ids[session_id] = cli_sid
                logger.info(
                    "cli_session_captured name=%s session=%s cli_session=%s",
                    self._name,
                    session_id,
                    cli_sid,
                )

    @staticmethod
    def _parse_ndjson_line(line: str, session_id: str) -> RuntimeEvent | None:
        """Parse a single NDJSON line into a RuntimeEvent.

        Handles three formats:
        - Claude CLI stream-json (``type: "assistant"`` / ``"tool_use"`` etc.)
        - Codex CLI legacy (``{"id","msg":{...}}`` envelope, deprecated)
        - Codex CLI new format (``item.started`` / ``item.completed`` /
          ``turn.completed`` / ``turn.failed``)
        """
        data = parse_json_line(line)
        if data is None:
            return create_event(RuntimeEventType.TEXT_DELTA, session_id, content=line + "\n")

        data = unwrap_codex_envelope(data)
        event_type = data.get("type", "")

        # --- Codex new format: item.* events ---
        if event_type in ("item.started", "item.updated", "item.completed"):
            return parse_codex_item_event(data, session_id)

        if event_type == "turn.completed":
            usage = data.get("usage")
            if isinstance(usage, dict):
                return parse_usage(usage, session_id)
            return None

        if event_type == "turn.failed":
            error_obj = data.get("error")
            msg = error_obj.get("message", "Turn failed") if isinstance(error_obj, dict) else "Turn failed"
            return create_event(
                RuntimeEventType.ERROR,
                session_id,
                error=AcpError(code=AcpErrorCode.UNKNOWN, message=str(msg)),
            )

        # --- Claude CLI / generic format ---
        if event_type in ("assistant", "text"):
            text = extract_text_from_event(data)
            if text:
                return create_event(RuntimeEventType.TEXT_DELTA, session_id, content=text)
            return None

        if event_type == "agent_message":
            text = data.get("message", "")
            if isinstance(text, str) and text:
                return create_event(RuntimeEventType.TEXT_DELTA, session_id, content=text)
            return None

        if event_type == "thinking":
            return parse_thinking(data, session_id)

        if event_type == "tool_use":
            return parse_tool_use(data, session_id)

        if event_type == "tool_result":
            return parse_tool_result(data, session_id)

        if event_type in ("usage", "token_count"):
            info = data.get("info")
            if isinstance(info, dict):
                return parse_usage(info, session_id)
            return parse_usage(data, session_id)

        if event_type == "result":
            usage = data.get("usage")
            if isinstance(usage, dict):
                return parse_usage(usage, session_id)
            return None

        if event_type in ("error", "stream_error"):
            return parse_error(data, session_id)

        return None


_MAX_TURNS_COMMANDS = frozenset({"claude"})


def _supports_max_turns(command: str) -> bool:
    """Check if a CLI command supports the ``--max-turns`` flag."""
    base = os.path.basename(command)
    return base in _MAX_TURNS_COMMANDS
