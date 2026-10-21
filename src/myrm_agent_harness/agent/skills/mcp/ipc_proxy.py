"""PTC IPC 服务端

通过 Unix Socket 为子进程提供 Programmatic Tool Calling 服务。
Agent-in-Sandbox 模式下，子进程通过 Unix Socket 与 Agent 主进程通信。

架构：
- Agent 主进程：运行 IPC Server，监听 Unix Socket
- 子进程（代码执行）：通过 Socket 文件与主进程通信
- 路由：skill_name == "__builtin__" → BuiltinToolRegistry
         其他 → MCPSkillProxyService
- 调用上下文：每个请求设置 ``IPCCallContext`` 到 ContextVar，
  让 ``notify`` 等内置 handler 取到 session_id /
  workspace_root，而无需污染全局或显式参数透传。

[INPUT]
- (none)

[OUTPUT]
- IPCCallContext: Frozen per-call context (session_id, workspace_root, trace_id).
- get_ipc_call_context: ContextVar accessor for builtin handlers.
- MCPIPCRequest / MCPIPCResponse: Wire types.
- MCPIPCServer: Unix Socket server; routes requests to BuiltinToolRegistry or MCPSkillProxyService.
- start_mcp_ipc_server / stop_mcp_ipc_server: Lifecycle helpers.
- get_mcp_trace_nonce: Accessor for the marker nonce the host uses to authenticate
  in-script call markers on stdout.

[POS]
PTC IPC backbone. Hosts the Unix-Socket server, wire schemas, and the per-call
context that lets builtin handlers reach session-scoped state.
"""

import asyncio
import hmac
import json
import logging
import os
import secrets
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from myrm_agent_harness.core.network.ipc_socket import (
    SOCKET_DIR_MODE,
    SOCKET_FILE_MODE,
)
from myrm_agent_harness.utils import os_compat

logger = logging.getLogger(__name__)

DEFAULT_MAX_CALLS_PER_SESSION = 50
"""Per-session IPC tool-call budget.

MCP PTC scripts loop over tools; without a ceiling a runaway script becomes an
unbounded external-API amplifier. 50 matches ``PtcConfig.max_tool_calls`` so both
PTC tracks share one number: measured orchestration scripts on this machine issue
0-3 callsites, so the ceiling only ever catches a runaway loop.
"""


@dataclass(frozen=True, slots=True)
class IPCCallContext:
    """Per-call context for IPC handlers (notify/...).

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
    agent_id: str | None = None
    """Agent identity for MCP scope-gate policy lookup; distinct from session_id."""
    workspace_root: str | None = None
    readonly_workspace: bool = False
    """True when the caller runs under a read-only capability handle.

    Sent explicitly instead of relying on the capability ContextVar: the IPC
    handler runs in the server's asyncio task, which captured the ContextVar at
    server-start time, so it cannot observe the calling run's handle.
    """
    auth_token: str | None = None
    """Per-process bearer token; the server rejects requests that omit or fake it."""


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

    def __init__(self, socket_path: str, max_calls_per_session: int = DEFAULT_MAX_CALLS_PER_SESSION):
        """初始化 IPC 服务端

        Args:
            socket_path: Unix Socket 文件路径
            max_calls_per_session: 单会话工具调用预算上限
        """
        self.socket_path = socket_path
        self._server: asyncio.Server | None = None
        self._running = False
        self._max_calls_per_session = max_calls_per_session
        self._session_calls: dict[str, int] = {}
        self._tcp_port: int = 0
        self.auth_token: str = secrets.token_urlsafe(32)
        self.trace_nonce: str = secrets.token_hex(16)
        """Nonce that authenticates in-script call markers on stdout.

        The generated client stamps every call marker with it. The host only accepts
        markers carrying this exact value, so text returned by a tool — a web page, an
        API payload — cannot forge a citation or truncate a genuine marker by embedding
        the marker delimiters. Rotated per server instance, i.e. per process. Callers
        obtain this value through ``get_mcp_trace_nonce`` rather than reading the server
        object, so a stopped server degrades to "no markers trusted" instead of stale
        acceptance.
        """

    async def start(self) -> None:
        """启动 IPC 服务端"""
        if self._running:
            logger.warning("MCP IPC Server already running")
            return

        if os_compat.IS_WIN:
            # Windows asyncio runs ProactorEventLoop, whose create_unix_connection raises
            # NotImplementedError, so the AF_UNIX path cannot work there. Bind loopback
            # TCP on an ephemeral port instead; the bearer token remains the boundary.
            self._server = await asyncio.start_server(self._handle_client, "127.0.0.1", 0)
            sockets = self._server.sockets
            if not sockets:
                raise RuntimeError("MCP IPC server bound no TCP socket")
            self._tcp_port = int(sockets[0].getsockname()[1])
            self._running = True
            logger.info(f"MCP IPC Server started at tcp://127.0.0.1:{self._tcp_port}")
            return

        # 私有目录（0700）：同机其他用户无法预建或连接 socket。
        # umask 在创建瞬间生效，消除 mkdir 与 chmod 之间被 co-tenant 打开目录 fd 的窗口。
        socket_dir = Path(self.socket_path).parent
        previous_umask = os.umask(0o077)
        try:
            socket_dir.mkdir(parents=True, exist_ok=True, mode=SOCKET_DIR_MODE)
        finally:
            os.umask(previous_umask)
        os.chmod(socket_dir, SOCKET_DIR_MODE)

        # 删除已存在的 socket 文件
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        # 启动 Unix Socket 服务器
        self._server = await asyncio.start_unix_server(self._handle_client, path=self.socket_path)

        # 仅所有者可读写：访问控制由 token 与目录权限共同保证
        os.chmod(self.socket_path, SOCKET_FILE_MODE)

        self._running = True
        logger.info(f"MCP IPC Server started at {self.socket_path}")

    @property
    def tcp_port(self) -> int:
        """Loopback TCP port when the server runs on the non-POSIX transport, else 0."""
        return self._tcp_port

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

            if not self._authorize(request.auth_token):
                logger.warning(f"{log_prefix} Rejected unauthorized IPC request")
                return MCPIPCResponse(
                    success=False, error="Unauthorized: invalid or missing auth token"
                ).model_dump_json()

            budget_error = self._consume_call_budget(request.session_id)
            if budget_error is not None:
                logger.warning(f"{log_prefix} Session budget exhausted: {request.session_id}")
                return MCPIPCResponse(success=False, error=budget_error).model_dump_json()

            policy_error = self._check_read_only_policy(request)
            if policy_error is not None:
                logger.warning(f"{log_prefix} Blocked by read-only policy: {request.skill_name}.{request.tool_name}")
                return MCPIPCResponse(success=False, error=policy_error).model_dump_json()

            path_error = self._check_path_policy(request)
            if path_error is not None:
                logger.warning(
                    f"{log_prefix} Blocked by path policy: {request.skill_name}.{request.tool_name} - {path_error}"
                )
                return MCPIPCResponse(success=False, error=path_error).model_dump_json()

            scope_error = self._check_scope_gate(request)
            if scope_error is not None:
                logger.warning(
                    f"{log_prefix} Blocked by agent scope gate: {request.skill_name}.{request.tool_name} - {scope_error}"
                )
                return MCPIPCResponse(success=False, error=scope_error).model_dump_json()

            logger.info(f"{log_prefix} Request: {request.skill_name}.{request.tool_name}")

            # Per-call context for builtin handlers (notify/...).
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
                        request.skill_name,
                        request.tool_name,
                        request.params,
                        trace_id=tid,
                        session_id=request.session_id or "-",
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

    def _authorize(self, token: str | None) -> bool:
        """Constant-time bearer-token check.

        The token is minted per server process and handed to the child through its
        environment, so a local process cannot forge a ``session_id`` and inject
        events into another conversation.
        """
        if not token:
            return False
        return hmac.compare_digest(token, self.auth_token)

    def _consume_call_budget(self, session_id: str | None) -> str | None:
        """Account one tool call against the session budget.

        Budgets are per session. A request without ``session_id`` has no bucket to
        account against, so it is not charged (the caller is already constrained by
        the authenticated socket and the read-only policy).

        Returns an error message when the budget is exhausted, else ``None``.
        """
        if not session_id:
            return None
        used = self._session_calls.get(session_id, 0)
        if used >= self._max_calls_per_session:
            return (
                f"Session tool-call budget exhausted: {used}/{self._max_calls_per_session} "
                "calls used. Summarise results and finish the script."
            )
        self._session_calls[session_id] = used + 1
        return None

    def _check_read_only_policy(self, request: MCPIPCRequest) -> str | None:
        """Enforce the caller's read-only scope on MCP calls made from scripts.

        The direct Function-Calling path drops or blocks non-read-only MCP tools
        inside a read-only sandbox. Scripts bypassed that filtering entirely, so a
        read-only verifier could still mutate external state through PTC. This is
        the enforcement point for that path.

        Returns an error message when blocked, else ``None``.
        """
        from myrm_agent_harness.agent.skills.mcp.builtin_registry import BUILTIN_SKILL_NAME

        # Builtins (notify) do not touch external state.
        if not request.readonly_workspace or request.skill_name == BUILTIN_SKILL_NAME:
            return None

        from myrm_agent_harness.core.security.tool_registry.registry import (
            get_ptc_safety_metadata,
        )

        entry = get_ptc_safety_metadata(request.skill_name, request.tool_name)
        if entry is not None and entry[0].is_read_only:
            return None
        return (
            f"MCP tool '{request.skill_name}.{request.tool_name}' is blocked: the calling run "
            "is in a read-only sandbox. Only tools declaring readOnlyHint may run here."
        )

    def _check_path_policy(self, request: MCPIPCRequest) -> str | None:
        """Enforce workspace path policy on tool calls made from scripts."""
        if not request.workspace_root or not isinstance(request.params, dict):
            return None

        path_keys = ("path", "file_path", "target", "destination", "filepath")
        target_path = None
        for k in path_keys:
            val = request.params.get(k)
            if isinstance(val, str) and val.strip():
                target_path = val.strip()
                break
        if not target_path:
            return None

        from myrm_agent_harness.agent.security.checks import check_path_policy
        from myrm_agent_harness.agent.security.types import PathPolicy, PermissionAction

        action, reason = check_path_policy(target_path, PathPolicy(), request.workspace_root)
        if action == PermissionAction.DENY:
            return f"Path policy violation: {reason}"
        return None

    def _check_scope_gate(self, request: MCPIPCRequest) -> str | None:
        """Enforce employee/agent-scoped MCP discovery gate policies."""
        from myrm_agent_harness.agent.sub_agents.mcp_scope_gate.scope_gate import (
            EmployeeScopedMcpDiscoveryGate,
        )
        from myrm_agent_harness.agent.sub_agents.mcp_scope_gate.types import (
            EmployeeToolScopeViolationError,
        )

        agent_id = request.agent_id
        if not agent_id:
            return None

        gate = EmployeeScopedMcpDiscoveryGate.get_instance()
        if not gate.get_policy(agent_id):
            return None

        server_name = request.skill_name
        if server_name.startswith("mcp_") and server_name.endswith("_skill"):
            server_name = server_name[4:-6]

        try:
            gate.verify_tool_invocation(agent_id, server_name, request.tool_name)
        except EmployeeToolScopeViolationError as e:
            return f"Agent scope violation: {e.reason}"
        return None


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


def get_mcp_trace_nonce() -> str | None:
    """Return the live marker nonce, or None when no IPC server is running.

    The host uses this to authenticate in-script call markers. Returning None once the
    server is gone makes marker parsing fail closed: output from a previous process can no
    longer be replayed into ``sources``, and a stopped server means no citation metadata
    rather than trusting an old nonce.
    """
    server = _ipc_server
    if server is None or not server._running:
        return None
    return server.trace_nonce
