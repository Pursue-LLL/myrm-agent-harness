"""Subagent state extraction utilities.

Extracts complete execution state from child agents for checkpoint save.

[INPUT]
- agent.base_agent::BaseAgent (POS: Agent 基类)

[OUTPUT]
- extract_subagent_state_sync: 同步提取子Agent状态
- extract_subagent_state_async: 异步提取子Agent状态（含checkpointer消息）

[POS]
Subagent state extraction utility. Extracts complete execution state
(messages/context/stats) from LangGraph checkpointer or _last_context for checkpoint save.

"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.agent.sub_agents.checkpoint.state_snapshot import (
    project_run_statistics,
    sanitize_persistable_context,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from myrm_agent_harness.agent.base_agent import BaseAgent

logger = get_agent_logger(__name__)


def extract_subagent_state_sync(child_agent: BaseAgent, task_id: str) -> dict[str, object]:
    """从子Agent提取完整执行状态（同步版本）.

    从_last_context和last_run_stats提取可同步获取的状态。
    适用于signal handler context。

    Args:
        child_agent: 子Agent实例
        task_id: 任务ID

    Returns:
        Dict containing:
        - messages: 空列表（同步无法获取LangChain messages）
        - context: Agent运行时上下文（dict）
        - stats: 运行统计信息（dict）
        - progress: 执行进度（0.0-1.0）
        - last_tool: 最后执行的工具名（从stats提取）

    Note:
        同步版本适用于signal handler，只提取_last_context和last_run_stats。
        完整的异步状态提取（LangGraph checkpointer）见extract_subagent_state_async。
    """
    context: dict[str, object] = {}
    stats: dict[str, object] = {}
    progress = 0.0
    last_tool: str | None = None

    if hasattr(child_agent, "_last_context"):
        context = sanitize_persistable_context(child_agent._last_context)
        logger.debug("[subagent:%s] Extracted context (keys=%s)", task_id, list(context.keys()))

    if child_agent.last_run_stats:
        stats, progress = project_run_statistics(child_agent.last_run_stats)
        logger.debug("[subagent:%s] Extracted stats (duration=%.1fs)", task_id, stats["duration_seconds"])

    return {
        "messages": [],
        "context": context,
        "stats": stats,
        "progress": progress,
        "last_tool": last_tool,
    }


async def extract_subagent_state_async(child_agent: BaseAgent, task_id: str) -> dict[str, object]:
    """从子Agent提取完整执行状态（异步版本）.

    直接调用BaseAgent.get_checkpoint_state()统一接口。

    Args:
        child_agent: 子Agent实例
        task_id: 任务ID（作为thread_id传递给checkpointer）

    Returns:
        Dict containing:
        - messages: 完整LangChain messages（从checkpointer提取）
        - context: Agent运行时上下文（dict）
        - stats: 运行统计信息（dict）
        - progress: 执行进度（0.0-1.0）
        - last_tool: 最后执行的工具名

    Note:
        复用BaseAgent.get_checkpoint_state()方法，避免代码重复。
        如果提取失败，fallback到同步版本。
    """
    try:
        state = await child_agent.get_checkpoint_state(thread_id=task_id)
        logger.debug(
            "[subagent:%s] Extracted complete state via get_checkpoint_state (messages=%d, last_tool=%s)",
            task_id,
            len(state.get("messages", [])),
            state.get("last_tool"),
        )
        return state
    except Exception as e:
        logger.warning(
            "[subagent:%s] Failed to extract state via get_checkpoint_state: %s, falling back to sync",
            task_id,
            e,
        )
        # Fallback to synchronous extraction
        return extract_subagent_state_sync(child_agent, task_id)
