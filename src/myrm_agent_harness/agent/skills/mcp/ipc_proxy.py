"""PTC IPC 服务端

通过 Unix Socket 为子进程提供 Programmatic Tool Calling 服务。
Agent-in-Sandbox 模式下，子进程通过 Unix Socket 与 Agent 主进程通信。

架构：
- Agent 主进程：运行 IPC Server，监听 Unix Socket
- 子进程（代码执行）：通过 Socket 文件与主进程通信
- 路由：skill_name == "__builtin__" → BuiltinToolRegistry
         其他 → MCPSkillProxyService
- 调用上下文：每个请求设置 ``IPCCallContext`` 到 ContextVar，
  让 ``session_store`` / ``notify`` 等内置 handler 取到 session_id /
  workspace_root，而无需污染全局或显式参数透传。

[INPUT]
- (none)

[OUTPUT]
- IPCCallContext: Frozen per-call context (session_id, workspace_root, trace_id).
- get_ipc_call_context: ContextVar accessor for builtin handlers.
- MCPIPCRequest / MCPIPCResponse: Wire types.
- MCPIPCServer: Unix Socket server; routes requests to BuiltinToolRegistry or MCPSkillProxyService.
- start_mcp_ipc_server / stop_mcp_ipc_server: Lifecycle helpers.

[POS]
PTC IPC backbone. Hosts the Unix-Socket server, wire schemas, and the per-call
context that lets builtin handlers reach session-scoped state.
"""

import asyncio
import json
import logging
import os
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class IPCCallContext:
    """Per-call context for IPC handlers (session_store/notify/...).

    Set by the IPC server before dispatching to a builtin handler. Read via
    :func:`get_ipc_call_context`. Frozen so handlers cannot mutate it.
    """

    session_id: str | None
    workspace_root: str | None
    trace_id: str


_ipc_call_context: ContextVar[IPCCallContext | None] = ContextVar("ipc_call_context", default=None)


def get_ipc_call_context() -> IPCCallContext | None:
    """Return the current IPC call context, or None if outside an IPC dispatch."""
    return _ipc_call_context.get()


class MCPIPCRequest(BaseModel):
    """PTC IPC 请求"""

    skill_name: str
    tool_name: str
    params: dict[str, object]
    trace_id: str = ""
    session_id: str | None = None
    workspace_root: str | None = None


class MCPIPCResponse(BaseModel):
    """MCP IPC 响应"""

    success: bool
    result: object | None = None
    error: str | None = None


class MCPIPCServer:
    """MCP IPC 服务端

    通过 Unix Socket 为沙箱环境提供 MCP 工具调用服务。
    """

    _REQUEST_TIMEOUT = 120.0
    _SHUTDOWN_TIMEOUT = 5.0

    def __init__(self, socket_path: str):
        """初始化 IPC 服务端

        Args:
            socket_path: Unix Socket 文件路径
        """
        self.socket_path = socket_path
        self._server: asyncio.Server | None = None
        self._running = False

    async def start(self) -> None:
        """启动 IPC 服务端"""
        if self._running:
            logger.warning("MCP IPC Server already running")
            return

        # 确保 socket 文件所在目录存在
        socket_dir = Path(self.socket_path).parent
        socket_dir.mkdir(parents=True, exist_ok=True)

        # 删除已存在的 socket 文件
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        # 启动 Unix Socket 服务器
        self._server = await asyncio.start_unix_server(self._handle_client, path=self.socket_path)

        # 设置 socket 文件权限（允许 Docker 容器访问）
        os.chmod(self.socket_path, 0o666)

        self._running = True
        logger.info(f"MCP IPC Server started at {self.socket_path}")

    async def stop(self) -> None:
        """停止 IPC 服务端"""
        if not self._running:
            return

        self._running = False

        if self._server:
            self._server.close()
            try:
                await asyncio.wait_for(self._server.wait_closed(), timeout=self._SHUTDOWN_TIMEOUT)
            except TimeoutError:
                logger.warning(f"IPC Server wait_closed timed out after {self._SHUTDOWN_TIMEOUT}s, forcing shutdown")
            self._server = None

        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        logger.info("MCP IPC Server stopped")

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """处理客户端连接

        协议格式：
        - 请求：4字节长度 + JSON数据
        - 响应：4字节长度 + JSON数据
        """
        try:
            while True:
                length_bytes = await reader.readexactly(4)
                length = int.from_bytes(length_bytes, "big")

                if length <= 0 or length > 10 * 1024 * 1024:
                    logger.error(f"Invalid message length: {length}")
                    break

                data = await reader.readexactly(length)
                message = data.decode("utf-8")

                try:
                    response = await asyncio.wait_for(self._process_request(message), timeout=self._REQUEST_TIMEOUT)
                except TimeoutError:
                    logger.error(f"IPC request timed out after {self._REQUEST_TIMEOUT}s")
                    response = MCPIPCResponse(
                        success=False, error=f"Request timed out after {self._REQUEST_TIMEOUT}s"
                    ).model_dump_json()

                response_bytes = response.encode("utf-8")
                writer.write(len(response_bytes).to_bytes(4, "big"))
                writer.write(response_bytes)
                await writer.drain()

        except asyncio.IncompleteReadError:
            pass
        except Exception as e:
            logger.error(f"IPC client handler error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()

    async def _process_request(self, message: str) -> str:
        """处理 MCP 调用请求

        Args:
            message: JSON 格式的请求消息

        Returns:
            JSON 格式的响应消息
        """
        tid = "-"
        try:
            request_data = json.loads(message)
            request = MCPIPCRequest.model_validate(request_data)

            tid = request.trace_id[:8] if request.trace_id else "-"
            log_prefix = f"[IPC:{tid}]"

            logger.info(f"{log_prefix} Request: {request.skill_name}.{request.tool_name}")

            # Per-call context for builtin handlers (session_store/notify/...).
            # ContextVar is task-local, so concurrent IPC clients stay isolated.
            ctx_token = _ipc_call_context.set(
                IPCCallContext(
                    session_id=request.session_id,
                    workspace_root=request.workspace_root,
                    trace_id=tid,
                )
            )
            try:
                from myrm_agent_harness.agent.skills.mcp.builtin_registry import BUILTIN_SKILL_NAME

                if request.skill_name == BUILTIN_SKILL_NAME:
                    from myrm_agent_harness.agent.skills.mcp.builtin_registry import get_builtin_tool_registry

                    registry = get_builtin_tool_registry()
                    result = await registry.dispatch(request.tool_name, request.params, tid)
                else:
                    from myrm_agent_harness.agent.skills.mcp.proxy_service import get_mcp_skill_proxy_service

                    service = get_mcp_skill_proxy_service()
                    result = await service.invoke_tool(
                        request.skill_name, request.tool_name, request.params, trace_id=tid
                    )
            finally:
                _ipc_call_context.reset(ctx_token)

            response = MCPIPCResponse(success=True, result=result)
            logger.info(f"{log_prefix} Success: {request.skill_name}.{request.tool_name}")

        except Exception as e:
            error_msg = f"{type(e).__name__}: {e!s}"
            logger.error(f"[IPC:{tid}] Failed: {error_msg}")
            response = MCPIPCResponse(success=False, error=error_msg)

        return response.model_dump_json()


# 全局 IPC 服务端实例
_ipc_server: MCPIPCServer | None = None


async def start_mcp_ipc_server(socket_path: str) -> MCPIPCServer:
    """启动全局 MCP IPC 服务端

    Args:
        socket_path: Unix Socket 文件路径

    Returns:
        IPC 服务端实例
    """
    global _ipc_server

    if _ipc_server is not None and _ipc_server._running:
        return _ipc_server

    _ipc_server = MCPIPCServer(socket_path)
    await _ipc_server.start()
    return _ipc_server


async def stop_mcp_ipc_server() -> None:
    """停止全局 MCP IPC 服务端"""
    global _ipc_server

    if _ipc_server is not None:
        await _ipc_server.stop()
        _ipc_server = None


def get_mcp_ipc_server() -> MCPIPCServer | None:
    """获取全局 MCP IPC 服务端实例"""
    return _ipc_server
