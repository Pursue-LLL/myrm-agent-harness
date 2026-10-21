"""LangGraph 中断 → 流式事件转换

[INPUT]
- core.events.types::AgentEventType (POS: 事件类型契约)
- agent.streaming.interrupt_identity::encode_interrupt_id (POS: 卡片 id = 中断 id + 轮次)

[OUTPUT]
- INTERRUPT_ID_KEY: 流事件与 resume 载荷共用的键，携带卡片 id
- interrupt_events: 把一个 `__interrupt__` 分片里的每个中断转换为带卡片 id 的流事件

[POS]
图在多个任务上同时挂起时（并行子 agent 各自要审批），每个中断都必须是一张可单独作答的卡片。
事件带上卡片 id（LangGraph 的中断 id 加该任务已消费的答复数，见 `interrupt_identity.py`），客户端作答时原样回传
（见 `_internals/resume_addressing.py`），答复只会落到它所针对的那一次挂起上，不会落到同一任务的下一次挂起，
也不会落到别的任务的挂起上。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from myrm_agent_harness.agent.streaming.interrupt_identity import encode_interrupt_id
from myrm_agent_harness.core.events.types import AgentEventType
from myrm_agent_harness.utils.logger_utils import get_agent_logger

logger = get_agent_logger(__name__)

INTERRUPT_ID_KEY = "interruptId"


def interrupt_events(
    interrupts: Sequence[object], message_id: str, rounds: Mapping[str, int] | None
) -> list[dict[str, object]]:
    """One stream event per interrupt the graph paused on; interrupts whose value is not a dict are skipped.

    ``rounds`` is the round each interrupt's task is at (a task absent from it has not been answered yet). ``None``
    means the rounds are unknown, so the events carry no card id and the client falls back to its id-less handling.
    """
    events: list[dict[str, object]] = []
    for interrupt in interrupts:
        value = getattr(interrupt, "value", None)
        if not isinstance(value, dict):
            continue
        event: dict[str, object] = {"type": _event_type(value), "data": value, "messageId": message_id}
        interrupt_id = getattr(interrupt, "id", None)
        if rounds is not None and isinstance(interrupt_id, str) and interrupt_id:
            event[INTERRUPT_ID_KEY] = encode_interrupt_id(interrupt_id, rounds.get(interrupt_id, 0))
        events.append(event)
    return events


def _event_type(value: dict[str, object]) -> str:
    if value.get("type") == "ask_question":
        logger.info("Agent execution suspended for clarification")
        return AgentEventType.CLARIFICATION_REQUIRED.value
    if value.get("action_type") == "swarm_fission":
        logger.info("Agent execution yielded for Swarm Fission")
        return "swarm_fission"
    action_requests = value.get("actionRequests")
    if isinstance(action_requests, list) and action_requests:
        logger.info("Agent execution suspended for tool approval")
        return AgentEventType.TOOL_APPROVAL_REQUEST.value
    logger.info("Agent execution suspended for approval")
    return AgentEventType.APPROVAL_REQUIRED.value
