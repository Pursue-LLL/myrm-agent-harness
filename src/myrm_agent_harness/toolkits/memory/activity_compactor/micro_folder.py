"""Micro-window activity folder implementing algorithmic deduplication and debouncing.

[INPUT]
- Internal: models.py (RawActivityEvent, MicroActivitySlice, ActivityActionType)
- External: collections, uuid, datetime

[OUTPUT]
- MicroActivityFolder: Folds 10-minute bursts of raw desktop events into concise slices with zero LLM tokens.

[POS]
Harness framework algorithmic tier eliminating mechanical noise and window thrashing.
"""

import uuid
from collections import Counter
from datetime import datetime

from .models import ActivityActionType, MicroActivitySlice, RawActivityEvent


class MicroActivityFolder:
    """Algorithmic folder debouncing high-frequency events into concise 10-minute slices."""

    def __init__(self, idle_threshold_seconds: float = 180.0) -> None:
        self.idle_threshold_seconds = idle_threshold_seconds

    def fold_window(
        self,
        events: list[RawActivityEvent],
        window_start: datetime,
        window_end: datetime,
    ) -> MicroActivitySlice:
        """Fold a batch of raw activity events within a 10-minute window into a single slice."""
        if not events:
            return MicroActivitySlice(
                slice_id=f"micro_{uuid.uuid4().hex[:8]}",
                start_time=window_start,
                end_time=window_end,
                primary_app="System",
                raw_event_count=0,
                folded_summary="此时间窗口内无用户活跃操作（静默段）",
                unique_windows=[],
                is_idle=True,
                active_minutes=0.0,
            )

        # 1. Filter out pure idle silence and calculate active duration
        active_events: list[RawActivityEvent] = []
        total_active_seconds = 0.0

        for i, ev in enumerate(events):
            if ev.action_type == ActivityActionType.IDLE_SILENCE:
                continue

            # Check gap with previous event for idle drop
            if i > 0:
                gap = (ev.timestamp - events[i - 1].timestamp).total_seconds()
                if gap > self.idle_threshold_seconds:
                    # Skip idle gap
                    pass
                else:
                    total_active_seconds += min(gap, 60.0)
            else:
                total_active_seconds += 5.0

            active_events.append(ev)

        active_minutes = round(total_active_seconds / 60.0, 1)

        if not active_events:
            return MicroActivitySlice(
                slice_id=f"micro_{uuid.uuid4().hex[:8]}",
                start_time=window_start,
                end_time=window_end,
                primary_app="Idle",
                raw_event_count=len(events),
                folded_summary="全段判定为非活跃静默空闲",
                unique_windows=[],
                is_idle=True,
                active_minutes=0.0,
            )

        # 2. Cluster by Application and Window Title
        app_counts: Counter[str] = Counter(ev.app_name for ev in active_events)
        primary_app = app_counts.most_common(1)[0][0]

        unique_windows: list[str] = []
        seen_windows: set[str] = set()
        for ev in active_events:
            title = ev.window_title.strip()
            if title and title not in seen_windows:
                seen_windows.add(title)
                unique_windows.append(title)

        # 3. Categorize Action Clusters (e.g. commands run, files edited)
        terminal_cmds: list[str] = []
        for ev in active_events:
            if ev.action_type == ActivityActionType.TERMINAL_CMD and ev.event_payload:
                cmd = ev.event_payload.strip()
                if cmd and cmd not in terminal_cmds:
                    terminal_cmds.append(cmd)

        # 4. Generate Objective Objective Folded Summary
        summary_clauses: list[str] = []
        summary_clauses.append(f"主要在 {primary_app} 中操作")

        if len(unique_windows) == 1:
            summary_clauses.append(f"专注工作区: {unique_windows[0]}")
        elif len(unique_windows) > 1:
            summary_clauses.append(f"涉及 {len(unique_windows)} 个工作区/标签 ({', '.join(unique_windows[:2])})")

        if terminal_cmds:
            summary_clauses.append(f"执行命令: {', '.join(terminal_cmds[:3])}")

        folded_summary = " · ".join(summary_clauses)

        return MicroActivitySlice(
            slice_id=f"micro_{uuid.uuid4().hex[:8]}",
            start_time=window_start,
            end_time=window_end,
            primary_app=primary_app,
            raw_event_count=len(events),
            folded_summary=folded_summary,
            unique_windows=unique_windows[:5],
            is_idle=False,
            active_minutes=active_minutes,
        )
