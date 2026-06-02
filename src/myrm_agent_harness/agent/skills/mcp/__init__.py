"""MCP Skills — Agent-layer MCP skill transformation.

将 MCP Tools 转换为 Agent 内部使用的 SkillMetadata。

MCP (Model Context Protocol) 是通用的工具提供能力，位于 toolkits/mcp/。
此模块负责将 MCP 提供的工具转换为 Agent 内部的技能表示。
子进程通过 Unix Socket IPC 回调 Agent 主进程调用 MCP 工具。
"""

from myrm_agent_harness.toolkits.mcp import MCPConfig

from .core_generator import MCPSkillGenerator
from .executor import SkillExecutionContext, SkillExecutor, skill_executor
from .ipc_proxy import (
    IPCCallContext,
    MCPIPCServer,
    get_ipc_call_context,
    get_mcp_ipc_server,
    start_mcp_ipc_server,
    stop_mcp_ipc_server,
)
from .proxy_service import MCPInvokeResult, MCPSkillProxyService, get_mcp_skill_proxy_service, handle_mcp_invoke

__all__ = [
    "IPCCallContext",
    "MCPConfig",
    "MCPIPCServer",
    "MCPInvokeResult",
    "MCPSkillGenerator",
    "MCPSkillProxyService",
    "SkillExecutionContext",
    "SkillExecutor",
    "get_ipc_call_context",
    "get_mcp_ipc_server",
    "get_mcp_skill_proxy_service",
    "handle_mcp_invoke",
    "skill_executor",
    "start_mcp_ipc_server",
    "stop_mcp_ipc_server",
]
