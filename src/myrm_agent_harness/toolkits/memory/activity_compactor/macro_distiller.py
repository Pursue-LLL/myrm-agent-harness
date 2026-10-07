"""Macro milestone distiller consolidating micro activity slices into 6-hour business folds.

[INPUT]
- Internal: models.py (MicroActivitySlice, MacroMilestoneFold)
- External: collections, uuid, datetime

[OUTPUT]
- MacroMilestoneDistiller: Distills up to 36 micro-slices into macro milestones without spammy noise.

[POS]
- Harness framework layer implementation of ChatGPT Desktop Skysight-style 6-hour
  macro consolidation tier (Topic 01 Item 87).
- Strict typing applied: No `any` types allowed.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime

from myrm_agent_harness.toolkits.memory.activity_compactor.models import (
    MacroMilestoneFold,
    MicroActivitySlice,
)


class MacroMilestoneDistiller:
    """Consolidates sequential 10-minute micro slices into structured 6-hour macro folds."""

    def __init__(self, confidence_floor: float = 0.85) -> None:
        self.confidence_floor = confidence_floor

    def distill_window(
        self,
        slices: list[MicroActivitySlice],
        window_start: datetime,
        window_end: datetime,
    ) -> MacroMilestoneFold:
        """Aggregate micro slices into a single macro milestone fold."""
        fold_id = f"macro_{uuid.uuid4().hex[:8]}"

        if not slices:
            return MacroMilestoneFold(
                fold_id=fold_id,
                start_time=window_start,
                end_time=window_end,
                milestone_summary="本 6 小时周期内未捕获到活跃计算机操作记录。",
                key_activities=[],
                micro_slices_count=0,
                tags=["idle"],
                confidence=1.0,
            )

        active_slices = [s for s in slices if not s.is_idle and s.raw_event_count > 0]
        if not active_slices:
            return MacroMilestoneFold(
                fold_id=fold_id,
                start_time=window_start,
                end_time=window_end,
                milestone_summary="本 6 小时周期主要为静默待机状态，无实质性任务产出。",
                key_activities=[],
                micro_slices_count=len(slices),
                tags=["idle", "standby"],
                confidence=0.95,
            )

        # 1. Primary application breakdown
        app_counts: Counter[str] = Counter(s.primary_app for s in active_slices)
        dominant_apps = [app for app, _ in app_counts.most_common(3)]

        # 2. Extract key activity statements
        key_activities: list[str] = []
        for s in active_slices:
            if s.folded_summary and s.folded_summary not in key_activities:
                key_activities.append(s.folded_summary)

        # 3. Tag categorization based on dominant tools and window titles
        tags: list[str] = []
        all_text = " ".join(dominant_apps + key_activities).lower()
        if any(k in all_text for k in ("code", "py", "ts", "rs", "git", "vim", "ide", "editor")):
            tags.append("development")
        if any(k in all_text for k in ("test", "pytest", "vitest", "assert", "fail", "pass")):
            tags.append("testing")
        if any(k in all_text for k in ("chrome", "browser", "doc", "wiki", "web")):
            tags.append("research")
        if any(k in all_text for k in ("terminal", "bash", "zsh", "docker", "ssh")):
            tags.append("ops")
        if not tags:
            tags.append("general_work")

        # 4. Formulate consolidated milestone summary
        total_active_mins = sum(s.active_minutes for s in active_slices)
        summary = (
            f"持续工作约 {total_active_mins:.1f} 分钟，主用工具为 {', '.join(dominant_apps)}；"
            f"推进了 {len(key_activities)} 项细分任务动作。"
        )

        return MacroMilestoneFold(
            fold_id=fold_id,
            start_time=window_start,
            end_time=window_end,
            milestone_summary=summary,
            key_activities=key_activities[:8],
            micro_slices_count=len(slices),
            tags=tags,
            confidence=max(self.confidence_floor, 0.95),
        )
