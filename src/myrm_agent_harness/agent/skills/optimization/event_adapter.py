"""EventLog Adapter for Skill Execution Provider

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- .protocols.SkillExecutionProvider (POS: 执行事件提供者抽象接口)
- agent.event_log.protocol.EventLogBackend (POS: EventLog后端接口)

[OUTPUT]
- EventLogAdapter: EventLog适配器类

[POS]
EventLog adapter (framework layer). Implements the SkillExecutionProvider protocol for event-driven data collection.

"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from .protocols import SkillExecutionProvider, SkillExecutionSample

if TYPE_CHECKING:
    from myrm_agent_harness.agent.event_log.protocols import EventLogBackend
    from myrm_agent_harness.agent.event_log.types import StructuredEvent

logger = logging.getLogger(__name__)


class EventLogAdapter(SkillExecutionProvider):
    """EventLog适配器

    实现SkillExecutionProvider Protocol，从EventLog查询skill执行数据。

    Args:
        event_log_backend: EventLog后端
    """

    def __init__(self, event_log_backend: EventLogBackend):
        self.event_log_backend = event_log_backend

    async def get_skill_executions(
        self, skill_id: str, days: int = 7, session_id: str | None = None
    ) -> list[SkillExecutionSample]:
        """从EventLog获取skill执行样本

        查询逻辑：
        1. 获取所有session IDs（或单个session）
        2. 查询tool_start, tool_complete, tool_error事件
        3. 按tool_call_id配对事件
        4. 重构为SkillExecutionSample对象

        Args:
            skill_id: Skill ID
            days: 最近N天
            session_id: 可选的session过滤

        Returns:
            SkillExecutionSample列表
        """
        samples: list[SkillExecutionSample] = []

        try:
            # 1. 获取session IDs
            if session_id:
                session_ids = [session_id]
            else:
                session_ids = await self.event_log_backend.get_all_session_ids()

            # 2. 查询每个session的events
            cutoff_time = datetime.now() - timedelta(days=days)

            for sid in session_ids:
                events = await self.event_log_backend.get_events(sid)

                # 3. 过滤和配对events
                tool_events = self._filter_tool_events(events, skill_id, cutoff_time)
                paired_samples = self._pair_tool_events(tool_events, sid)

                samples.extend(paired_samples)

            return samples

        except Exception as e:
            logger.error(f"Failed to query EventLog: {e}")
            return []

    async def get_all_skill_ids(self) -> list[str]:
        """获取所有有执行记录的skill ID

        Returns:
            Skill ID列表
        """
        try:
            session_ids = await self.event_log_backend.get_all_session_ids()
            skill_ids: set[str] = set()

            for sid in session_ids:
                events = await self.event_log_backend.get_events(sid)

                for event in events:
                    if event.event_type in ["tool_start", "tool_complete", "tool_error"]:
                        tool_name = event.payload.get("tool_name", "")
                        if tool_name.startswith("skill_"):
                            skill_id = tool_name[6:]
                            skill_ids.add(skill_id)

            return list(skill_ids)

        except Exception as e:
            logger.error(f"Failed to get skill IDs: {e}")
            return []

    async def count_executions(self, skill_id: str, days: int = 7) -> int:
        """统计执行次数

        Args:
            skill_id: Skill ID
            days: 最近N天

        Returns:
            执行次数
        """
        samples = await self.get_skill_executions(skill_id, days)
        return len(samples)

    # ==================== Internal Methods ====================

    def _filter_tool_events(
        self, events: list[StructuredEvent], skill_id: str, cutoff_time: datetime
    ) -> list[StructuredEvent]:
        """过滤tool相关事件

        Args:
            events: 所有事件
            skill_id: Skill ID
            cutoff_time: 时间截止点

        Returns:
            过滤后的事件列表
        """
        tool_name = f"skill_{skill_id}"

        filtered = []
        for event in events:
            # 检查事件类型
            if event.event_type not in ["tool_start", "tool_complete", "tool_error"]:
                continue

            # 检查tool名称
            if event.payload.get("tool_name") != tool_name:
                continue

            # 检查时间（如果event有timestamp）
            event_time = event.payload.get("timestamp")
            if event_time:
                if isinstance(event_time, str):
                    try:
                        event_time = datetime.fromisoformat(event_time)
                    except ValueError:
                        continue

                if event_time < cutoff_time:
                    continue

            filtered.append(event)

        return filtered

    def _pair_tool_events(self, events: list[StructuredEvent], session_id: str) -> list[SkillExecutionSample]:
        """配对tool_start和tool_complete/tool_error事件

        Args:
            events: 过滤后的事件列表
            session_id: Session ID

        Returns:
            SkillExecutionSample列表
        """
        # 按tool_call_id分组
        event_groups: dict[str, dict[str, StructuredEvent]] = {}

        for event in events:
            tool_call_id = event.payload.get("tool_call_id")
            if not tool_call_id:
                continue

            if tool_call_id not in event_groups:
                event_groups[tool_call_id] = {}

            event_groups[tool_call_id][event.event_type] = event

        # 配对并重构
        samples: list[SkillExecutionSample] = []

        for group in event_groups.values():
            start_event = group.get("tool_start")
            complete_event = group.get("tool_complete")
            error_event = group.get("tool_error")

            if not start_event:
                continue

            # 确定是否成功
            success = complete_event is not None

            # 计算执行时间
            if complete_event:
                end_event = complete_event
            elif error_event:
                end_event = error_event
            else:
                continue  # 没有结束事件，跳过

            duration_seconds = self._calculate_duration(start_event, end_event)

            # 提取token count
            token_count = end_event.payload.get("token_count", 0)

            # 提取timestamp
            executed_at = self._extract_timestamp(start_event)

            # 提取skill_id
            tool_name = start_event.payload.get("tool_name", "")
            skill_id = tool_name[6:] if tool_name.startswith("skill_") else tool_name

            # 错误消息
            error_message = error_event.payload.get("error") if error_event else None

            sample = SkillExecutionSample(
                skill_id=skill_id,
                executed_at=executed_at,
                success=success,
                duration_seconds=duration_seconds,
                token_count=token_count,
                user_feedback=None,  # EventLog暂不包含用户反馈
                session_id=session_id,
                error_message=error_message,
            )

            samples.append(sample)

        return samples

    def _calculate_duration(self, start_event: StructuredEvent, end_event: StructuredEvent) -> float:
        """计算执行时间

        Args:
            start_event: 开始事件
            end_event: 结束事件

        Returns:
            执行时间（秒）
        """
        start_time = self._extract_timestamp(start_event)
        end_time = self._extract_timestamp(end_event)

        duration = (end_time - start_time).total_seconds()
        return max(duration, 0.0)

    def _extract_timestamp(self, event: StructuredEvent) -> datetime:
        """提取事件时间戳

        Args:
            event: 事件

        Returns:
            datetime对象
        """
        timestamp = event.payload.get("timestamp")

        if isinstance(timestamp, datetime):
            return timestamp
        elif isinstance(timestamp, str):
            try:
                return datetime.fromisoformat(timestamp)
            except ValueError:
                pass

        # 默认返回当前时间
        return datetime.now()
