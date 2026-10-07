"""Grounded dreaming idle scheduler and REM backfill pipeline.

[POS]
记忆认知闲时整合调度中心。管理人类睡眠期记忆整合生理机制的后台模拟，
涵盖空闲交互超时判定、夜间定时窗口检测、REM 历史会话窗口回溯重放管道，
以及多项目隔离作用域做梦编排。

[INPUT]
- fragments: 跨会话对话记忆碎片列表
- trigger_reason: 做梦触发原因枚举
- target_project_id: 可选的目标项目范围约束

[OUTPUT]
- DreamingTriggerReason: 做梦触发动因枚举
- GroundedDreamingScheduler: 闲时做梦自主调度器与编排引擎
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, time
from enum import StrEnum

from myrm_agent_harness.toolkits.memory.dreaming.engine import GroundedDreamingEngine
from myrm_agent_harness.toolkits.memory.dreaming.models import (
    DreamDiaryEntry,
    DreamSessionFragment,
)
from myrm_agent_harness.toolkits.memory.dreaming.provenance import (
    ProjectScopeIsolationGuard,
)

logger = logging.getLogger(__name__)


class DreamingTriggerReason(StrEnum):
    """Reason triggering a grounded dreaming consolidation cycle."""

    IDLE_TIMEOUT = "idle_timeout"
    NIGHTLY_WINDOW = "nightly_window"
    REM_BACKFILL = "rem_backfill"
    MANUAL = "manual"


class GroundedDreamingScheduler:
    """Orchestrates idle memory consolidation and REM historical backfill cycles."""

    def __init__(
        self,
        engine: GroundedDreamingEngine | None = None,
        idle_inactivity_seconds: int = 1800,
        nightly_start_time: time = time(hour=2, minute=0),
        nightly_end_time: time = time(hour=5, minute=0),
    ) -> None:
        self._engine = engine or GroundedDreamingEngine()
        self._idle_inactivity_seconds = idle_inactivity_seconds
        self._nightly_start_time = nightly_start_time
        self._nightly_end_time = nightly_end_time
        self._last_interaction_time: datetime = datetime.now(UTC)

    def record_interaction(self, at: datetime | None = None) -> None:
        """Mark latest user interaction timestamp to reset idle counter."""
        self._last_interaction_time = at or datetime.now(UTC)

    def is_idle(self, now: datetime | None = None) -> bool:
        """Check whether system has exceeded idle inactivity threshold."""
        current = now or datetime.now(UTC)
        elapsed = (current - self._last_interaction_time).total_seconds()
        return elapsed >= self._idle_inactivity_seconds

    def is_within_nightly_window(self, now: datetime | None = None) -> bool:
        """Check whether current time falls within configured low-traffic nightly window."""
        current = now or datetime.now(UTC)
        t = current.time()
        if self._nightly_start_time <= self._nightly_end_time:
            return self._nightly_start_time <= t <= self._nightly_end_time
        # Overnight range wrapping around midnight (e.g., 23:00 to 04:00)
        return t >= self._nightly_start_time or t <= self._nightly_end_time

    def should_trigger_dreaming(self, now: datetime | None = None) -> tuple[bool, DreamingTriggerReason | None]:
        """Evaluate whether idle conditions or nightly maintenance warrants dreaming cycle."""
        current = now or datetime.now(UTC)
        if self.is_within_nightly_window(current):
            return True, DreamingTriggerReason.NIGHTLY_WINDOW
        if self.is_idle(current):
            return True, DreamingTriggerReason.IDLE_TIMEOUT
        return False, None

    def consolidate(
        self,
        fragments: Sequence[DreamSessionFragment],
        trigger_reason: DreamingTriggerReason,
        target_project_id: str | None = None,
    ) -> list[DreamDiaryEntry]:
        """Execute consolidation cycle over session fragments with scope filtering."""
        logger.info(
            "Initiating grounded dreaming cycle (reason=%s, fragments=%d, project_id=%s)",
            trigger_reason.value,
            len(fragments),
            target_project_id,
        )

        entries = self._engine.process_fragments(fragments, target_project_id=target_project_id)

        # Apply project scope isolation guard if target_project_id is specified
        if target_project_id is not None:
            filtered_entries: list[DreamDiaryEntry] = []
            for entry in entries:
                if ProjectScopeIsolationGuard.validate_scope(
                    entry.project_id, target_project_id, is_personal_profile=(entry.project_id is None)
                ):
                    filtered_entries.append(entry)
            entries = filtered_entries

        logger.info(
            "Grounded dreaming cycle completed: %d insights distilled into Dream Diary",
            len(entries),
        )
        return entries

    def run_rem_backfill(
        self,
        historical_fragments: Sequence[DreamSessionFragment],
        lookback_days: int = 7,
        target_project_id: str | None = None,
    ) -> list[DreamDiaryEntry]:
        """Execute REM historical backfill pipeline across past session fragments."""
        cutoff_seconds = lookback_days * 86400
        now = datetime.now(UTC)
        filtered_fragments = [
            f for f in historical_fragments
            if (now - f.extracted_at).total_seconds() <= cutoff_seconds
        ]
        logger.info(
            "REM historical backfill selected %d/%d fragments for lookback=%dd",
            len(filtered_fragments),
            len(historical_fragments),
            lookback_days,
        )
        return self.consolidate(
            fragments=filtered_fragments,
            trigger_reason=DreamingTriggerReason.REM_BACKFILL,
            target_project_id=target_project_id,
        )
