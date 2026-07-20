"""ACP protocol runtime backend.

Spawns an external ACP-compatible agent process (Claude Code, Codex CLI, etc.)
and communicates via the standard ACP JSON-RPC protocol over stdin/stdout.

[INPUT]
- toolkits.acp.types::BackendCapabilities, BackendStatus, McpServerConfig (POS: ACP runtime type definitions layer. Provides all ACP-related core abstractions and data structures, serving as the foundation for the entire ACP module.)
- toolkits.acp.event_bus::EventBus (POS: ACP event bus layer. Provides decoupled event dispatch mechanism for the Runtime system with session isolation and type filtering.)
- toolkits.code_execution.utils.workspace_path::WorkspacePathResolver (POS: Workspace path resolver with intelligent auto-detection.)

[OUTPUT]
- AcpRuntime: RuntimeBackend implementation using the ACP protocol (std...

[POS]
ACP protocol runtime backend.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.acp.event_bus import EventBus
from myrm_agent_harness.toolkits.acp.runtime._base import BaseRuntime, build_safe_env
from myrm_agent_harness.toolkits.acp.runtime.acp_callback import AcpCallbackHandler
from myrm_agent_harness.toolkits.acp.types import (
    BackendCapabilities,
    BackendStatus,
    McpServerConfig,
    RuntimeConfig,
    RuntimeEvent,
    RuntimeEventType,
    create_event,
)

if TYPE_CHECKING:
    from acp import ClientSideConnection
    from acp.aio_subprocess import Process

logger = logging.getLogger(__name__)


class AcpRuntime(BaseRuntime):
    """RuntimeBackend implementation using the ACP protocol (stdin/stdout JSON-RPC).

    Spawns an external agent process and communicates via the official ACP SDK.
    Supports session reuse, cancel, and resume.
    """

    def __init__(
        self,
        runtime_name: str,
        config: RuntimeConfig,
        *,
        event_bus: EventBus | None = None,
    ) -> None:
        super().__init__(runtime_name, config, backend_type="acp")
        self._conn: ClientSideConnection | None = None
        self._process: Process | None = None
        self._session_id: str | None = None
        self._ctx_manager: object | None = None
        self._handler: AcpCallbackHandler | None = None
        self._event_bus = event_bus

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
        if not self.is_alive:
            yield create_event(
                RuntimeEventType.STATUS_UPDATE, session_id, status="starting", message="Spawning ACP agent process"
            )
            await self._ensure_connection()

        if self._session_id is None:
            await self._create_session(mcp_servers=mcp_servers)

        handler = self._handler
        if handler is None:
            msg = "Handler not initialized"
            raise RuntimeError(msg)
        handler.reset()

        prompt_task = asyncio.create_task(self._run_prompt(prompt, handler))

        try:
            async for event in self._consume_events(handler):
                yield event
        finally:
            if not prompt_task.done():
                prompt_task.cancel()
            try:
                await prompt_task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.error("acp_prompt_task_failed name=%s", self._name, exc_info=True)

    async def _run_prompt(self, prompt: str, handler: AcpCallbackHandler) -> None:
        """Run the ACP prompt and signal completion via the handler's queue."""
        from acp.schema import TextContentBlock

        try:
            response = await self._conn.prompt(  # type: ignore[union-attr]
                prompt=[TextContentBlock(type="text", text=prompt)],
                session_id=self._session_id,  # type: ignore[arg-type]
            )
            handler.mark_done(response.stop_reason)
        except Exception as exc:
            handler.mark_done(f"error:{type(exc).__name__}")
            raise

    @staticmethod
    async def _consume_events(
        handler: AcpCallbackHandler,
    ) -> AsyncIterator[RuntimeEvent]:
        """Consume RuntimeEvents from the handler's queue in real-time."""
        while True:
            event = await handler.event_queue.get()
            if event is None:
                break
            yield event

    async def _do_cancel(self, session_id: str) -> None:
        if self._conn is not None and self._session_id is not None:
            await self._conn.cancel(session_id=self._session_id)

    async def _do_resume(self, session_id: str) -> bool:
        return self._session_id is not None and self.is_alive

    async def _do_close(self) -> None:
        if self._conn is not None and self._session_id is not None:
            try:
                await self._conn.close_session(session_id=self._session_id)
            except Exception:
                logger.debug("acp_close_session_failed name=%s", self._name, exc_info=True)

        if self._ctx_manager is not None:
            try:
                await self._ctx_manager.__aexit__(None, None, None)
            except Exception:
                logger.debug("acp_ctx_exit_failed name=%s", self._name, exc_info=True)
        else:
            if self._conn is not None:
                try:
                    await self._conn.close()
                except Exception:
                    logger.debug("acp_close_conn_failed name=%s", self._name, exc_info=True)
            if self._process is not None:
                with contextlib.suppress(ProcessLookupError):
                    self._process.terminate()

        self._conn = None
        self._process = None
        self._session_id = None
        self._ctx_manager = None
        self._handler = None

    async def _do_get_status(self) -> BackendStatus:
        if self.is_alive:
            return "ready"
        if self._process is not None and self._process.returncode is not None:
            return "error"
        return "stopped"

    # -- Internal --

    async def _ensure_connection(self) -> None:
        """Spawn the external agent process and establish ACP connection."""
        await self._do_close()

        from acp import PROTOCOL_VERSION, spawn_agent_process
        from acp.schema import ClientCapabilities, FileSystemCapabilities, Implementation

        self._handler = AcpCallbackHandler(
            self._config,
            session_id="",
            event_bus=self._event_bus,
        )
        safe_env = build_safe_env(self._config)
        from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import WorkspacePathResolver

        cwd = self._config.cwd or str(WorkspacePathResolver.resolve_workspace_root())

        command = self._config.command
        if command is None:
            msg = "AcpRuntime requires 'command' in RuntimeConfig"
            raise ValueError(msg)

        ctx = spawn_agent_process(
            self._handler,
            command,
            *self._config.args,
            env=safe_env,
            cwd=cwd,
        )
        self._ctx_manager = ctx
        conn, process = await ctx.__aenter__()
        self._conn = conn
        self._process = process
        self._alive = True

        await conn.initialize(
            protocol_version=PROTOCOL_VERSION,
            client_capabilities=ClientCapabilities(
                fs=FileSystemCapabilities(read_text_file=True, write_text_file=True),
                terminal=False,
            ),
            client_info=Implementation(name="myrm-acp-client", version="1.0.0"),
        )
        logger.info("acp_runtime_connected name=%s pid=%s", self._name, process.pid)

    async def _create_session(self, *, mcp_servers: list[McpServerConfig] | None = None) -> None:
        """Create a new ACP session."""
        if self._conn is None:
            msg = "Cannot create session: connection not established"
            raise RuntimeError(msg)

        from myrm_agent_harness.toolkits.code_execution.utils.workspace_path import WorkspacePathResolver

        cwd = self._config.cwd or str(WorkspacePathResolver.resolve_workspace_root())
        acp_mcp = _mcp_configs_to_acp_stdio(mcp_servers)
        if acp_mcp:
            response = await self._conn.new_session(cwd=cwd, mcp_servers=acp_mcp)
        else:
            response = await self._conn.new_session(cwd=cwd)
        self._session_id = response.session_id
        if self._handler is not None:
            self._handler.session_id = self._session_id
        logger.info("acp_runtime_session_created name=%s session_id=%s", self._name, self._session_id)


def _mcp_configs_to_acp_stdio(
    mcp_servers: list[McpServerConfig] | None,
) -> list[object] | None:
    if not mcp_servers:
        return None
    from acp.schema import EnvVariable, McpServerStdio

    return [
        McpServerStdio(
            name=server.name,
            command=server.command,
            args=list(server.args),
            env=[
                EnvVariable(name=key, value=value)
                for key, value in sorted((server.env or {}).items())
            ],
        )
        for server in mcp_servers
    ]
