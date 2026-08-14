"""Concurrency limiter middleware for subagent execution.

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- agent.sub_agents.registry::SUBAGENT_CONFIGS (POS: Subagent 配置注册表)
- langchain.agents.middleware::wrap_tool_call (POS: 工具调用中间件装饰器)
- langgraph.prebuilt.tool_node::ToolCallRequest (POS: 工具调用请求)

[OUTPUT]
- create_concurrency_limiter: 创建并发限制中间件的工厂函数
- get_subagent_semaphore: 获取特定 agent 类型的 semaphore

[POS]
Subagent concurrency limiter middleware. Limits concurrent execution count by agent_type to prevent resource exhaustion.

"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import wrap_tool_call
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from myrm_agent_harness.agent.sub_agents.registry import SUBAGENT_CONFIGS
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

_semaphores: dict[str, asyncio.Semaphore] = {}


def get_subagent_semaphore(agent_type: str) -> asyncio.Semaphore | None:
    """Get or lazily create semaphore for *agent_type*.

    Creates the semaphore on first access using the concurrency_limit from
    SUBAGENT_CONFIGS, so the registry can be populated at any time before first use.
    """
    sem = _semaphores.get(agent_type)
    if sem is not None:
        return sem

    cfg = SUBAGENT_CONFIGS.get(agent_type)
    if cfg is None:
        return None

    sem = asyncio.Semaphore(cfg.concurrency_limit)
    _semaphores[agent_type] = sem
    return sem


def create_concurrency_limiter():
    """Create concurrency limiter middleware for subagent operations.

    Automatically detects tools with 'agent_type' parameter and applies
    concurrency limits based on SUBAGENT_CONFIGS.

    Returns:
        Middleware function that limits concurrent subagent execution per type.
    """

    @wrap_tool_call  # type: ignore[arg-type]
    async def concurrency_limiter_middleware(
        request: ToolCallRequest, handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]
    ) -> ToolMessage | Command:
        """Limit concurrent execution for subagent spawn operations."""
        tool_args: dict[str, object] = request.tool_call.get("args") or {}  # type: ignore[assignment]
        agent_type_arg = tool_args.get("agent_type")

        if not isinstance(agent_type_arg, str) or not agent_type_arg:
            return await handler(request)

        semaphore = get_subagent_semaphore(agent_type_arg)
        if semaphore is None:
            return await handler(request)

        logger.info("Acquiring semaphore for agent_type=%s", agent_type_arg)
        async with semaphore:
            result = await handler(request)
        logger.info("Released semaphore for agent_type=%s", agent_type_arg)

        return result

    return concurrency_limiter_middleware
