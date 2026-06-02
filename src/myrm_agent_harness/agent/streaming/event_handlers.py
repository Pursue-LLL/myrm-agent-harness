"""LangGraph 流事件处理器

[INPUT]
- langchain_core.messages::AIMessage, (POS: Core message type definitions. All cross-channel communication data structures are defined here; zero I/O, pure data.)
- agent.streaming.step_builder::build_step_data (POS: Agent)
- agent.streaming.source_tracker::SourceTracker (POS: BaseAgent  SourceTracker)
- agent.types::AgentEventType, (POS: Provides ArtifactInfo, infer_language, infer_artifact_type.)

[OUTPUT]
- process_updates_chunk(): 处理 LangGraph updates 流 → 业务事件（含自动 sources 转发，空 AIMessage 过滤）
- process_messages_chunk(): 处理 LangGraph messages 流 → 消息块事件（含 LLM 控制 token 清洗、工具调用文本抑制）

[POS]
LangGraph stream event to business event transformer. Core event handler for BaseAgent.run().
Emits TOOL_IMAGE_OUTPUT for all image blocks in multimodal ToolMessage content
(base64 images from MCP tools, computer_use screenshots, etc.).

"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator, Generator
from typing import cast

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from myrm_agent_harness.agent.streaming.types import AgentEventType
from myrm_agent_harness.toolkits.code_execution.executors.models import (
    scrub_sensitive_info,
)
from myrm_agent_harness.utils.logger_utils import get_agent_logger
from myrm_agent_harness.utils.text_sanitizer import sanitize_llm_output

from ..types import AgentRunStatistics
from .source_tracker import SourceTracker
from .step_builder import build_step_data, get_step_key

logger = get_agent_logger(__name__)


# ==================== Updates 流处理 ====================


async def process_updates_chunk(
    data: dict[str, dict[str, object]],
    stats: AgentRunStatistics,
    message_id: str,
    collected_messages: list[BaseMessage] | None = None,
    source_tracker: SourceTracker | None = None,
) -> AsyncGenerator[dict[str, object]]:
    """处理 updates 流数据，转换为业务事件

    Args:
        data: LangGraph updates 流数据
        stats: 执行统计
        message_id: 消息 ID
        collected_messages: 可选，用于收集所有消息（Steering 重建 agent_input 用）
        source_tracker: 可选，会话级引用源追踪器（自动去重+转发 sources 事件）
    """
    for node_name, node_output in data.items():
        if not node_output:
            continue

        stats.node_execution_count += 1
        logger.debug(" Node execution [%s] (%d times)", node_name, stats.node_execution_count)

        # Handle LangGraph __interrupt__ events
        if node_name == "__interrupt__":
            # node_output is a tuple of Interrupt objects
            from langgraph.types import Interrupt

            if isinstance(node_output, tuple):
                for item in node_output:
                    if isinstance(item, Interrupt) and hasattr(item, "value"):
                        payload = item.value
                        action_requests = (
                            payload.get("actionRequests", [])
                            if isinstance(payload, dict)
                            else []
                        )
                        tool_names = [
                            str(r.get("action", "?"))
                            for r in action_requests
                            if isinstance(r, dict)
                        ] or ["unknown"]
                        logger.info(
                            "LangGraph interrupt triggered: %s", ", ".join(tool_names)
                        )
                        yield {
                            "type": AgentEventType.TOOL_APPROVAL_REQUEST.value,
                            "data": item.value,
                            "messageId": message_id,
                        }
            continue

        if "messages" not in node_output:
            continue

        messages = cast(list[object], node_output["messages"])
        for msg in messages:
            if collected_messages is not None and isinstance(msg, BaseMessage):
                if (
                    isinstance(msg, AIMessage)
                    and not msg.content
                    and not msg.tool_calls
                ):
                    logger.debug("Skipping empty AIMessage from collected_messages")
                else:
                    collected_messages.append(msg)

            if isinstance(msg, AIMessage) and msg.tool_calls:
                async for event in _handle_tool_calls(msg, stats, message_id):
                    yield event
            elif isinstance(msg, ToolMessage):
                async for event in _handle_tool_result(msg, message_id, source_tracker):
                    yield event
            elif isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
                logger.debug(" AI response: %s...", str(msg.content)[:100])


async def _handle_tool_calls(
    msg: AIMessage, stats: AgentRunStatistics, message_id: str
) -> AsyncGenerator[dict[str, object]]:
    """处理 AIMessage 中的工具调用"""
    for tc in msg.tool_calls:
        stats.tool_call_count += 1
        tool_name = tc.get("name", "")
        tool_args = tc.get("args", {})
        logger.debug(" Tool call: %s", tool_name)

        args_str = str(tool_args)[:200]
        if len(str(tool_args)) > 200:
            args_str += "..."
        logger.debug(" Args: %s", args_str)

        step_result = build_step_data(tool_name, tool_args)
        reason = tool_args.get("reason", "")
        step_key = step_result.get("step_key") or get_step_key(tool_name)

        yield {
            "type": AgentEventType.TASKS_STEPS.value,
            "step_key": step_key,
            "tool_call_id": tc.get("id"),
            "tool_name": tool_name,
            "reason": scrub_sensitive_info(reason),
            "data": step_result.get("data", []),
            "messageId": message_id,
        }


async def _handle_tool_result(
    msg: ToolMessage, message_id: str, source_tracker: SourceTracker | None = None
) -> AsyncGenerator[dict[str, object]]:
    """处理 ToolMessage（工具执行结果）

    当 source_tracker 存在时，自动完成：
    1. reviewing_sources 步骤（ProgressSteps UI 展示本次搜索来源）
    2. sources 事件（引用栏，去重后的增量来源）
    """
    tool_name = getattr(msg, "name", "unknown")
    status = getattr(msg, "status", "success")

    if status == "error":
        error_content = str(msg.content)[:500] if msg.content else "Unknown error"
        logger.warning(" Tool execution failed [%s]: %s", tool_name, error_content[:300])

        event = {
            "type": AgentEventType.TASKS_STEPS.value,
            "step_key": f"{get_step_key(tool_name)}_error",
            "tool_name": tool_name,
            "status": "error",
            "error": scrub_sensitive_info(error_content),
            "messageId": message_id,
        }

        # Propagate diagnostic metadata for business layer (server) to consume
        if error_category := msg.additional_kwargs.get("error_category"):
            event["error_category"] = str(error_category)

        if error_hint := msg.additional_kwargs.get("error_hint"):
            event["error_hint"] = str(error_hint)

        yield event

        if "Tool call limit exceeded" in error_content:
            yield {
                "type": AgentEventType.ENGINE_LIMIT_REACHED.value,
                "data": {
                    "limit_type": "max_tool_calls",
                    "tool_name": tool_name,
                    "message": error_content,
                },
                "messageId": message_id,
            }
        elif "max_replan_attempts exceeded" in error_content:
            yield {
                "type": AgentEventType.ENGINE_LIMIT_REACHED.value,
                "data": {
                    "limit_type": "max_replan_attempts",
                    "tool_name": tool_name,
                    "message": error_content,
                },
                "messageId": message_id,
            }

        return

    # Emit image events for multimodal tool outputs (e.g., MCP screenshots, computer_use)
    if isinstance(msg.content, list):
        for block in msg.content:
            if isinstance(block, dict) and block.get("type") == "image" and block.get("base64"):
                yield {
                    "type": AgentEventType.TOOL_IMAGE_OUTPUT.value,
                    "tool_name": tool_name,
                    "data": {
                        "base64": block["base64"],
                        "mime_type": block.get("mime_type", "image/jpeg"),
                    },
                    "messageId": message_id,
                }

    try:
        tool_metadata = _extract_tool_metadata(msg)

        if source_tracker and tool_metadata:
            async for source_event in _emit_source_events(
                tool_metadata, message_id, source_tracker
            ):
                yield source_event

    except Exception as e:
        logger.error(" Failed to send tool event: %s: %s", type(e).__name__, e)


def _extract_tool_metadata(msg: ToolMessage) -> dict[str, object]:
    """从 ToolMessage 中提取 metadata（支持 dict 和 JSON 字符串两种格式）"""
    if isinstance(msg.content, dict):
        return msg.content.get("metadata", {})

    if isinstance(msg.content, str) and msg.content.strip().startswith("{"):
        try:
            parsed = json.loads(msg.content)
            if isinstance(parsed, dict):
                return parsed.get("metadata", {})
        except json.JSONDecodeError:
            pass

    return {}


async def _emit_source_events(
    tool_metadata: dict[str, object], message_id: str, source_tracker: SourceTracker
) -> AsyncGenerator[dict[str, object]]:
    """通过 SourceTracker 发送引用相关事件

    1. reviewing_sources 步骤 → ProgressSteps UI（展示本次工具返回的来源）
    2. sources 事件 → 引用栏（仅新增的、去重后的来源）
    """
    new_sources = source_tracker.extract_and_add(tool_metadata)
    if not new_sources:
        return

    yield {
        "type": AgentEventType.TASKS_STEPS.value,
        "step_key": "reviewing_sources",
        "tool_name": None,
        "count": len(new_sources),
        "data": new_sources,
        "messageId": message_id,
    }

    yield {
        "type": AgentEventType.SOURCES.value,
        "data": new_sources,
        "messageId": message_id,
    }


# ==================== Messages 流处理 ====================


def process_messages_chunk(
    data: tuple[object, object], stats: AgentRunStatistics, message_id: str
) -> Generator[tuple[dict[str, object], bool]]:
    """处理 messages 流数据

    Yields:
        (事件字典, 是否为 tool_start 事件)
    """
    if not isinstance(data, tuple) or len(data) < 2:
        return

    message_chunk, metadata = data
    if metadata is None:
        return

    metadata_dict = cast(dict[str, object], metadata)
    if metadata_dict.get("langgraph_node") != "model":
        return

    content = getattr(message_chunk, "content", None)
    content_str = str(content) if content else ""

    reasoning_text = _extract_reasoning(message_chunk)
    if reasoning_text:
        yield (
            {
                "type": AgentEventType.REASONING.value,
                "data": reasoning_text,
                "messageId": message_id,
            },
            False,
        )

    is_tool_call = _is_tool_call_chunk(message_chunk)

    if content_str:
        # Myrm-Guard: Final global scrubbing for all LLM messages (even thoughts)
        from myrm_agent_harness.toolkits.code_execution.executors.models import (
            scrub_sensitive_info,
        )

        content_str = scrub_sensitive_info(sanitize_llm_output(content_str))

    # 如果检测到工具调用，则抑制文本回调，防止将 XML 标签或 JSON 暴露给用户
    if content_str and not is_tool_call:
        stats.message_chunk_count += 1
        yield (
            {
                "type": AgentEventType.MESSAGE.value,
                "data": content_str,
                "messageId": message_id,
            },
            False,
        )

    if is_tool_call:
        logger.debug(" 检测到工具调用，发送 tool_start 事件")
        yield (
            {
                "type": AgentEventType.TOOL_START.value,
                "messageId": message_id,
            },
            True,
        )


def _extract_reasoning(message_chunk: object) -> str:
    """Extract reasoning/thinking content from an LLM message chunk.

    Supports two formats:
    - ``additional_kwargs["reasoning_content"]`` (DeepSeek, OpenAI o-series)
    - ``content`` blocks with ``type="thinking"`` (Anthropic Claude)
    """
    kwargs: dict[str, object] = getattr(message_chunk, "additional_kwargs", {}) or {}
    rc = kwargs.get("reasoning_content")
    if isinstance(rc, str) and rc:
        return rc

    content = getattr(message_chunk, "content", None)
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "thinking":
                thinking = block.get("thinking")
                if isinstance(thinking, str) and thinking:
                    parts.append(thinking)
        if parts:
            return "".join(parts)

    return ""


def _is_tool_call_chunk(message_chunk: object) -> bool:
    """检查消息块是否是工具调用"""
    content_blocks = getattr(message_chunk, "content_blocks", None)
    is_tool_call_block = bool(
        content_blocks
        and any(
            isinstance(b, dict) and b.get("type") in ("tool_call", "tool_call_chunk")
            for b in content_blocks
        )
    )
    has_tool_calls = bool(getattr(message_chunk, "tool_calls", None))
    has_tool_call_chunks = bool(getattr(message_chunk, "tool_call_chunks", None))
    return is_tool_call_block or has_tool_calls or has_tool_call_chunks
