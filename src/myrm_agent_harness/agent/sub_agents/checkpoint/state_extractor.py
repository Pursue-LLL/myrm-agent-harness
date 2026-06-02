"""Subagent state extraction and restoration utilities.

Extracts and restores complete execution state from child agents for checkpoint save/resume.

[INPUT]
- agent.base_agent::BaseAgent (POS: Agent 基类)
- langchain_core.messages::BaseMessage (POS: LangChain 消息类型)

[OUTPUT]
- extract_subagent_state_sync: 同步提取子Agent状态
- extract_subagent_state_async: 异步提取子Agent状态（含checkpointer消息）
- restore_subagent_state: 恢复子Agent完整状态（消息+上下文）

[POS]
Subagent state extraction and restoration utility. Extracts complete execution state
(messages/context/stats) from LangGraph checkpointer or _last_context, and restores
them for checkpoint-based resumption.

"""

from __future__ import annotations

from typing import TYPE_CHECKING

from myrm_agent_harness.utils.logger_utils import get_agent_logger

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

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
        context = child_agent._last_context or {}
        logger.debug("[subagent:%s] Extracted context (keys=%s)", task_id, list(context.keys()))

    if child_agent.last_run_stats:
        stats = {
            "token_usage": child_agent.last_run_stats.token_usage.to_dict()
            if child_agent.last_run_stats.token_usage
            else {},
            "duration_seconds": child_agent.last_run_stats.duration_seconds,
            "status": child_agent.last_run_stats.status.value if child_agent.last_run_stats.status else "unknown",
        }
        progress = 1.0 if child_agent.last_run_stats.status else 0.5
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


async def restore_subagent_state(child_agent: BaseAgent, checkpoint_data: dict[str, object]) -> None:
    """恢复子Agent完整状态.

    从checkpoint_data恢复消息历史和运行时上下文到agent实例。
    如果agent有checkpointer，将消息写入checkpointer以恢复LangGraph状态。

    Args:
        child_agent: 子Agent实例
        checkpoint_data: checkpoint数据，包含：
            - messages: 序列化的LangChain消息列表
            - variables: 运行时上下文dict
            - progress: 执行进度
            - last_tool: 最后执行的工具名

    Raises:
        ValueError: checkpoint_data格式无效
    """
    messages: list[dict[str, object]] = checkpoint_data.get("messages", [])  # type: ignore[assignment]
    variables: dict[str, object] = checkpoint_data.get("variables", {})  # type: ignore[assignment]

    # 1. 恢复运行时上下文
    if variables:
        child_agent._last_context = dict(variables)
        logger.debug(
            "Restored runtime context (keys=%s)",
            list(variables.keys()),
        )

    # 2. 恢复消息到checkpointer
    if messages and child_agent.checkpointer is not None:
        restored_count = await _restore_messages_to_checkpointer(
            child_agent, messages
        )
        logger.info(
            "Restored %d/%d messages to checkpointer",
            restored_count,
            len(messages),
        )
    elif messages:
        logger.debug(
            "No checkpointer available, skipping message restoration (%d messages)",
            len(messages),
        )

    logger.info(
        "Subagent state restored (messages=%d, context_keys=%d)",
        len(messages),
        len(variables),
    )


async def _restore_messages_to_checkpointer(
    child_agent: BaseAgent,
    serialized_messages: list[dict[str, object]],
) -> int:
    """将序列化的消息写入checkpointer.

    反序列化消息并写入LangGraph checkpointer，恢复对话历史。

    Args:
        child_agent: 子Agent实例（必须有checkpointer）
        serialized_messages: 序列化的消息列表

    Returns:
        成功恢复的消息数量
    """
    from langgraph.checkpoint.base import Checkpoint

    messages: list[BaseMessage] = []
    for msg_dict in serialized_messages:
        msg = _deserialize_message(msg_dict)
        if msg is not None:
            messages.append(msg)

    if not messages:
        return 0

    # 构建checkpoint并写入
    try:
        checkpoint: Checkpoint = {
            "v": 1,
            "id": str(serialized_messages[-1].get("id", "")),
            "ts": str(serialized_messages[-1].get("timestamp", "")),
            "channel_values": {"messages": messages},
            "channel_versions": {},
            "versions_seen": {},
            "updated_channels": ["messages"],
        }
        config = {"configurable": {"thread_id": "restored"}}
        await child_agent.checkpointer.aput(config, checkpoint, {}, {})
        return len(messages)
    except Exception as e:
        logger.warning("Failed to restore messages to checkpointer: %s", e)
        return 0


def _deserialize_message(msg_dict: dict[str, object]) -> BaseMessage | None:
    """将序列化的消息字典反序列化为LangChain消息对象.

    Args:
        msg_dict: 序列化的消息字典，必须包含 'type' 和 'content' 字段

    Returns:
        LangChain消息对象，或None（如果反序列化失败）
    """
    from langchain_core.messages import (
        AIMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )

    msg_type = msg_dict.get("type", "")
    content = msg_dict.get("content", "")
    additional_kwargs = msg_dict.get("additional_kwargs", {})  # type: ignore[assignment]
    tool_calls = msg_dict.get("tool_calls", [])
    tool_call_id = msg_dict.get("tool_call_id", "")

    try:
        if msg_type == "human":
            return HumanMessage(
                content=content,
                additional_kwargs=additional_kwargs,  # type: ignore[arg-type]
            )
        if msg_type == "ai":
            return AIMessage(
                content=content,
                additional_kwargs=additional_kwargs,  # type: ignore[arg-type]
                tool_calls=tool_calls,  # type: ignore[arg-type]
            )
        if msg_type == "system":
            return SystemMessage(
                content=content,
                additional_kwargs=additional_kwargs,  # type: ignore[arg-type]
            )
        if msg_type == "tool":
            return ToolMessage(
                content=content,
                tool_call_id=tool_call_id,  # type: ignore[arg-type]
            )
        logger.warning("Unknown message type: %s", msg_type)
        return None
    except Exception as e:
        logger.warning("Failed to deserialize message (type=%s): %s", msg_type, e)
        return None
