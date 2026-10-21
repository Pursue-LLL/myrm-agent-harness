"""Session fan-out braking sentinel for dynamic cascade suppression.

Monitors the internal amplification of tool tasks and subagent calls spawned
within a single conversation turn, tripping safety brakes to prevent runaway loops.

[INPUT]
- __future__
- time
- throttle_types

[OUTPUT]
- FanOutBrakingSentinel

[POS]
Session fan-out braking sentinel for dynamic cascade suppression.
"""

from __future__ import annotations

import time

from .throttle_types import (
    BrakeSeverity,
    FanOutBrakeVerdict,
    FanOutLimitExceededError,
)


class FanOutBrakingSentinel:
    """Monitors per-session derived task counts and enforces tiered braking policies."""

    def __init__(
        self,
        soft_limit: int = 10,
        brake_limit: int = 15,
        hard_limit: int = 25,
    ) -> None:
        self.soft_limit = soft_limit
        self.brake_limit = brake_limit
        self.hard_limit = hard_limit
        self._session_counts: dict[str, int] = {}
        self._session_start_times: dict[str, float] = {}

    def record_derived_task(
        self,
        session_id: str,
        raise_on_hard_limit: bool = True,
    ) -> FanOutBrakeVerdict:
        """Register a new derived internal task (tool call / subagent invocation) and evaluate safety brakes."""
        if session_id not in self._session_start_times:
            self._session_start_times[session_id] = time.time()

        count = self._session_counts.get(session_id, 0) + 1
        self._session_counts[session_id] = count

        if count >= self.hard_limit:
            verdict = FanOutBrakeVerdict(
                severity=BrakeSeverity.HARD_BRAKE_FUSED,
                session_id=session_id,
                current_derived_tasks=count,
                soft_limit=self.soft_limit,
                hard_limit=self.hard_limit,
                should_throttle=True,
                should_fuse=True,
                rationale=f"Hard safety budget breached ({count} >= {self.hard_limit}). Execution fused.",
            )
            if raise_on_hard_limit:
                raise FanOutLimitExceededError(session_id, count, self.hard_limit)
            return verdict

        if count >= self.brake_limit:
            return FanOutBrakeVerdict(
                severity=BrakeSeverity.SOFT_BRAKE,
                session_id=session_id,
                current_derived_tasks=count,
                soft_limit=self.soft_limit,
                hard_limit=self.hard_limit,
                should_throttle=True,
                should_fuse=False,
                rationale=f"Soft brake threshold exceeded ({count} >= {self.brake_limit}). Throttling concurrency.",
            )

        if count >= self.soft_limit:
            return FanOutBrakeVerdict(
                severity=BrakeSeverity.WARNING,
                session_id=session_id,
                current_derived_tasks=count,
                soft_limit=self.soft_limit,
                hard_limit=self.hard_limit,
                should_throttle=False,
                should_fuse=False,
                rationale=f"Elevated task amplification detected ({count} >= {self.soft_limit}).",
            )

        return FanOutBrakeVerdict(
            severity=BrakeSeverity.NORMAL,
            session_id=session_id,
            current_derived_tasks=count,
            soft_limit=self.soft_limit,
            hard_limit=self.hard_limit,
            should_throttle=False,
            should_fuse=False,
            rationale="Task derivation count within normal operating boundaries.",
        )

    def reset_turn(self, session_id: str) -> None:
        """Reset the derived task counter at the boundary of a new user conversational turn."""
        self._session_counts.pop(session_id, None)
        self._session_start_times.pop(session_id, None)

    def get_count(self, session_id: str) -> int:
        """Return the current derived task count for a given session."""
        return self._session_counts.get(session_id, 0)

    def render_governance_markdown(self, session_id: str) -> str:
        """Render a GitHub Flavored Markdown card showing fan-out governance metrics."""
        count = self.get_count(session_id)
        start_t = self._session_start_times.get(session_id, time.time())
        elapsed_s = round(time.time() - start_t, 2)

        lines: list[str] = [
            f"### 🛡️ 扇出效应抑制与任务流治理看板: `{session_id}`",
            f"- **当前轮次累计派生任务数**: `{count}`",
            f"- **预警阈值**: `{self.soft_limit}` 步",
            f"- **软刹车限流阈值**: `{self.brake_limit}` 步",
            f"- **硬熔断防线**: `{self.hard_limit}` 步",
            f"- **单轮耗时**: `{elapsed_s}s`",
            "",
        ]

        if count >= self.hard_limit:
            lines.extend(
                [
                    "> [!CAUTION]",
                    f"> **[硬熔断保护已触发]** 该会话派生任务数已达到硬防线 ({count}/{self.hard_limit})，已自动切断级联派生，保护系统免受雪崩坍塌。",
                ]
            )
        elif count >= self.brake_limit:
            lines.extend(
                [
                    "> [!WARNING]",
                    f"> **[软刹车介入]** 任务派生速率偏高 ({count}/{self.brake_limit})，已启用反压串行排队机制，强制大模型优先收敛结论。",
                ]
            )
        elif count >= self.soft_limit:
            lines.extend(
                [
                    "> [!NOTE]",
                    f"> **[扇出预警]** 内部任务流开始放大 ({count}/{self.soft_limit})，系统持续跟踪资源消耗。",
                ]
            )
        else:
            lines.extend(
                [
                    "> [!TIP]",
                    "> 任务派生处于健康安全区间，未触碰任何限流阈值。",
                ]
            )

        return "\n".join(lines)
