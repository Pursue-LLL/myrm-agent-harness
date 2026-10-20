"""巡检告警定向回写专属智能体会话路由模块。

支持将 Cron 产出的异常报警或分析简报直连注入指定 Bot 对话流（Bot Chat），
并具备调用深度熔断门禁（防回环递归唤醒风暴）与目标缺失平滑降级能力。

[INPUT]
- __future__
- dataclasses
- logging
- time
- typing

[OUTPUT]
- logger
- RoutedBotMessage
- RoutingResult
- BotChatRouter

[POS]
巡检告警定向回写专属智能体会话路由模块。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_CALL_DEPTH = 1


@dataclass(frozen=True)
class RoutedBotMessage:
    """定向投递至智能体专属会话的消息实体。"""

    message_id: str
    target_agent_id: str
    origin_cron_id: str
    content: str
    call_depth: int
    created_at_mono: float
    extra_metadata: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RoutingResult:
    """消息路由执行结果。"""

    success: bool
    message_id: Optional[str]
    action: str
    reason: str


class BotChatRouter:
    """巡检告警智能体专属会话路由器。"""

    def __init__(self, registered_bot_ids: Optional[List[str]] = None) -> None:
        self._registered_bot_ids: List[str] = (
            list(registered_bot_ids) if registered_bot_ids is not None else []
        )
        self._dispatched_messages: Dict[str, RoutedBotMessage] = {}

    def register_bot(self, agent_id: str) -> None:
        """登记合法受管的智能体标识。"""
        if agent_id not in self._registered_bot_ids:
            self._registered_bot_ids.append(agent_id)

    def route_alert_to_bot(
        self,
        origin_cron_id: str,
        target_agent_id: str,
        alert_content: str,
        call_depth: int = 0,
    ) -> RoutingResult:
        """将巡检告警原子投递至指定智能体专属会话。

        若调用深度超出上限则熔断；若目标智能体未注册则平滑降级。
        """
        # 1. 深度熔断门禁：防回环递归唤醒风暴
        if call_depth >= _MAX_CALL_DEPTH:
            logger.warning(
                "Call depth %d reached for cron %s to bot %s; dropping cascade",
                call_depth,
                origin_cron_id,
                target_agent_id,
            )
            return RoutingResult(
                success=False,
                message_id=None,
                action="CASCADE_BLOCKED",
                reason=f"Call depth {call_depth} reached maximum {_MAX_CALL_DEPTH}",
            )

        # 2. 目标智能体存活校验与平滑降级
        if self._registered_bot_ids and target_agent_id not in self._registered_bot_ids:
            logger.warning(
                "Target bot %s not found for cron %s; fallback gracefully",
                target_agent_id,
                origin_cron_id,
            )
            return RoutingResult(
                success=False,
                message_id=None,
                action="FALLBACK_DEFAULT_CHANNEL",
                reason=f"Target bot '{target_agent_id}' is not registered or archived",
            )

        # 3. 构造并派发结构化消息
        msg_id = f"bot_msg_{origin_cron_id}_{int(time.monotonic() * 1000)}"
        message = RoutedBotMessage(
            message_id=msg_id,
            target_agent_id=target_agent_id,
            origin_cron_id=origin_cron_id,
            content=alert_content,
            call_depth=call_depth + 1,
            created_at_mono=time.monotonic(),
            extra_metadata={
                "injected_from_cron": "true",
                "interactive_followup_allowed": "true",
            },
        )
        self._dispatched_messages[msg_id] = message

        logger.info(
            "Successfully routed alert %s from cron %s to bot %s",
            msg_id,
            origin_cron_id,
            target_agent_id,
        )
        return RoutingResult(
            success=True,
            message_id=msg_id,
            action="ROUTED_TO_BOT_CHAT",
            reason=f"Alert successfully injected into bot {target_agent_id} context",
        )

    def get_dispatched_message(self, message_id: str) -> Optional[RoutedBotMessage]:
        """获取已派发的消息记录。"""
        return self._dispatched_messages.get(message_id)
