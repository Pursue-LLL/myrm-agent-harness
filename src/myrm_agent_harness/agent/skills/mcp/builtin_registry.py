"""PTC 内置工具注册表

为 Programmatic Tool Calling 提供内置工具注册和分发。
子进程通过 IPC 调用 skill_name="__builtin__" 时，由本模块路由到对应的 handler。

架构：
- BuiltinToolEntry: 单个工具的注册信息（handler + 描述 + 参数 schema）
- BuiltinToolRegistry: 全局注册表，提供 register / dispatch / get_ptc_description

[INPUT]
- agent.skills.mcp.builtin_notify::notify_handler (POS: Realtime progress notification handler.)
- agent.skills.mcp.builtin_session_store::session_store_handler, session_load_handler, session_keys_handler (POS: Cross-call key-value persistence for PTC scripts.)

[OUTPUT]
- BuiltinToolEntry: Registered handler + description + parameter schema + return type.
- BuiltinToolRegistry: Process-wide registry with register / dispatch / get_ptc_description.
- get_builtin_tool_registry: Lazy singleton accessor (registers session_store/load/keys, notify).

[POS]
PTC builtin tool registry & dispatcher. Sole entry point for PTC-only builtins
(session persistence, notify) exposed under the ``myrm_tools`` namespace in bash
Python scripts. Web search/fetch use native LLM tools + PTC RPC stubs instead.
"""

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)

BUILTIN_SKILL_NAME = "__builtin__"


BuiltinHandler = Callable[[dict[str, object]], Awaitable[object]]


@dataclass(frozen=True, slots=True)
class BuiltinToolEntry:
    """PTC 内置工具注册条目"""

    handler: BuiltinHandler
    description: str
    parameters: dict[str, str]
    return_type: str = "str"


class BuiltinToolRegistry:
    """PTC 内置工具注册表

    启动时注册工具，运行时通过 dispatch 分发请求。
    """

    def __init__(self) -> None:
        self._tools: dict[str, BuiltinToolEntry] = {}

    def register(
        self,
        name: str,
        handler: BuiltinHandler,
        description: str,
        parameters: dict[str, str],
        return_type: str = "str",
    ) -> None:
        """注册一个内置工具

        Args:
            name: 工具名称（对应 IPC 请求的 tool_name）
            handler: async handler，接收 dict 参数，返回 JSON-serialisable 结果
                     (handlers needing session context can call
                     ``get_ipc_call_context()`` to retrieve session_id / workspace_root).
            description: 工具描述（注入 bash_code_execute_tool 描述供 LLM 感知）
            parameters: 参数签名描述 {param_name: type_desc}
            return_type: 返回值类型说明（用于 PTC 描述生成，默认 str）
        """
        if name in self._tools:
            logger.warning(f"PTC builtin tool '{name}' already registered, overwriting")
        self._tools[name] = BuiltinToolEntry(
            handler=handler,
            description=description,
            parameters=parameters,
            return_type=return_type,
        )
        logger.info(f"PTC builtin tool registered: {name}")

    async def dispatch(self, tool_name: str, params: dict[str, object], trace_id: str = "-") -> object:
        """分发 PTC 调用到对应 handler

        Args:
            tool_name: 工具名称
            params: 调用参数
            trace_id: 调用链追踪 ID（前 8 位）

        Returns:
            工具执行结果（JSON-serialisable 任意对象）

        Raises:
            KeyError: 工具未注册
        """
        entry = self._tools.get(tool_name)
        if entry is None:
            available = ", ".join(sorted(self._tools.keys())) or "(none)"
            raise KeyError(f"PTC builtin tool '{tool_name}' not found. Available: {available}")

        start = time.monotonic()
        result = await entry.handler(params)
        elapsed_ms = (time.monotonic() - start) * 1000
        logger.info(f"[PTC:{trace_id}] builtin {tool_name} completed in {elapsed_ms:.0f}ms")
        return result

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def get_ptc_description(self) -> str:
        """生成 PTC 内置工具描述（注入 bash_code_execute_tool description）

        Returns:
            格式化的工具描述字符串，供 LLM 感知可用的 myrm_tools 命名空间
        """
        if not self._tools:
            return ""

        lines = [
            "\n## PTC Built-in Tools",
            "Available via `import myrm_tools` in Python scripts (in skills: `from tools.{name} import {name}`):",
        ]
        for name, entry in sorted(self._tools.items()):
            params_str = ", ".join(f"{k}: {v}" for k, v in entry.parameters.items())
            lines.append(f"- `myrm_tools.{name}({params_str})` — {entry.description} -> {entry.return_type}")

        return "\n".join(lines)

    @property
    def tool_names(self) -> list[str]:
        return sorted(self._tools.keys())


_registry: BuiltinToolRegistry | None = None


def get_builtin_tool_registry() -> BuiltinToolRegistry:
    """获取全局 PTC 内置工具注册表（懒初始化）"""
    global _registry
    if _registry is None:
        _registry = BuiltinToolRegistry()
        _register_default_tools(_registry)
    return _registry


def _register_default_tools(registry: BuiltinToolRegistry) -> None:
    """Register PTC-only builtins (no native LLM tool equivalent).

    Web search/fetch are not registered here: bind ``web_search_tool`` /
    ``web_fetch_tool`` on the agent for native + PTC RPC stub access. PTC-only
    builtins below avoid duplicating web APIs in bash tool description.
    """
    from myrm_agent_harness.agent.skills.mcp.builtin_notify import notify_handler
    from myrm_agent_harness.agent.skills.mcp.builtin_session_store import (
        session_keys_handler,
        session_load_handler,
        session_store_handler,
    )

    registry.register(
        name="session_store",
        handler=session_store_handler,
        description=(
            "Persist a JSON-serialisable value under a string key for later "
            "PTC calls in the same session. Survives across bash_code_execute_tool "
            "invocations (Python is otherwise stateless)."
        ),
        parameters={"key": "str", "value": "JSON-serialisable"},
        return_type="None",
    )
    registry.register(
        name="session_load",
        handler=session_load_handler,
        description=("Load a value previously stored via session_store. Returns None when the key is missing."),
        parameters={"key": "str"},
        return_type="object | None",
    )
    registry.register(
        name="session_keys",
        handler=session_keys_handler,
        description="List all keys currently stored via session_store.",
        parameters={},
        return_type="list[str]",
    )
    registry.register(
        name="notify",
        handler=notify_handler,
        description=(
            "Push a real-time progress message from inside a PTC script. "
            "Fire-and-forget: the script keeps running while the UI shows an "
            "inline activity card (grouped by ``category``). Optional "
            "``progress`` 0-100, ``step_index`` and ``total_steps`` drive a "
            "real progress bar; use ``category`` (e.g. 'crawl') to merge "
            "related calls into one card. Rate-limited to 10 req/s per "
            "session — overflow calls are dropped silently."
        ),
        parameters={
            "message": "str",
            "level": "'info' | 'warn' | 'alert' = 'info'",
            "progress": "int 0..100 | None = None",
            "step_index": "int >=1 | None = None",
            "total_steps": "int >=1 | None = None",
            "category": "str <=32 chars | None = None",
        },
        return_type="None",
    )
