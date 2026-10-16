"""LangGraph 中断 → 流式事件转换

[INPUT]
- core.events.types::AgentEventType (POS: 事件类型契约)

[OUTPUT]
- INTERRUPT_ID_KEY: 流事件与 resume 载荷共用的键，携带 LangGraph 的中断 id
- interrupt_events: 把一个 `__interrupt__` 分片里的每个中断转换为带 id 的流事件

[POS]
图在多个任务上同时挂起时（并行子 agent 各自要审批），每个中断都必须是一张可单独作答的卡片。
事件带上 LangGraph 的中断 id，客户端作答时原样回传（见 `_internals/resume_addressing.py`），
答复只会落到它所针对的那个中断上，不会落到后来挂起的别的中断上。
"""

from __future__ import annotations

from collections.abc import Sequence

from myrm_agent_harness.core.events.types import AgentEventType
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

INTERRUPT_ID_KEY = "interruptId"


def interrupt_events(interrupts: Sequence[object], message_id: str) -> list[dict[str, object]]:
    """One stream event per interrupt the graph paused on; interrupts whose value is not a dict are skipped."""
    events: list[dict[str, object]] = []
    for interrupt in interrupts:
        value = getattr(interrupt, "value", None)
        if not isinstance(value, dict):
            continue
        event: dict[str, object] = {"type": _event_type(value), "data": value, "messageId": message_id}
        interrupt_id = getattr(interrupt, "id", None)
        if isinstance(interrupt_id, str) and interrupt_id:
            event[INTERRUPT_ID_KEY] = interrupt_id
        events.append(event)
    return events


def _event_type(value: dict[str, object]) -> str:
    if value.get("type") == "ask_question":
        logger.warning("Agent execution suspended for clarification")
        return AgentEventType.CLARIFICATION_REQUIRED.value
    if value.get("action_type") == "swarm_fission":
        logger.warning("Agent execution yielded for Swarm Fission")
        return "swarm_fission"
    action_requests = value.get("actionRequests")
    if isinstance(action_requests, list) and action_requests:
        logger.warning("Agent execution suspended for tool approval")
        return AgentEventType.TOOL_APPROVAL_REQUEST.value
    logger.warning("Agent execution suspended for approval")
    return AgentEventType.APPROVAL_REQUIRED.value
