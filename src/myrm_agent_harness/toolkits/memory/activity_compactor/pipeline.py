"""Hierarchical activity compactor pipeline orchestrating 10min/6h/24h compaction tiers.

[INPUT]
- Internal: models.py, micro_folder.py, macro_distiller.py
- External: datetime, uuid, typing

[OUTPUT]
- HierarchicalActivityCompactorPipeline: Unified pipeline coordinator with telemetry metrics.

[POS]
- Harness framework layer implementation of ChatGPT Desktop Skysight-style
  multi-tier event logging, folding, distillation, and telemetry pipeline (Topic 01 Item 87).
- Strict typing applied: No `any` types allowed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from myrm_agent_harness.toolkits.memory.activity_compactor.macro_distiller import (
    MacroMilestoneDistiller,
)
from myrm_agent_harness.toolkits.memory.activity_compactor.micro_folder import (
    MicroActivityFolder,
)
from myrm_agent_harness.toolkits.memory.activity_compactor.models import (
    ActivityActionType,
    CompactorPipelineConfig,
    CompactorPipelineTelemetry,
    DailyPreferenceArchive,
    MacroMilestoneFold,
    MicroActivitySlice,
    RawActivityEvent,
)


class HierarchicalActivityCompactorPipeline:
    """Orchestrates 10-minute algorithmic folding, 6-hour milestone distillation,

    and 24-hour long-term preference synthesis with telemetry.
    """

    def __init__(self, config: CompactorPipelineConfig | None = None) -> None:
        self.config = config or CompactorPipelineConfig()
        self.micro_folder = MicroActivityFolder(
            idle_threshold_seconds=float(self.config.idle_threshold_seconds),
        )
        self.macro_distiller = MacroMilestoneDistiller()

        # Buffers and history stores
        self._raw_event_buffer: list[RawActivityEvent] = []
        self._micro_slices: list[MicroActivitySlice] = []
        self._macro_folds: list[MacroMilestoneFold] = []
        self._daily_archives: list[DailyPreferenceArchive] = []

        # Telemetry counters
        self._total_raw_events_count = 0
        self._idle_events_dropped_count = 0

    def ingest_event(self, event: RawActivityEvent) -> None:
        """Ingest a single raw activity event into buffer."""
        self._raw_event_buffer.append(event)
        self._total_raw_events_count += 1
        if event.action_type == ActivityActionType.IDLE_SILENCE:
            self._idle_events_dropped_count += 1

    def ingest_batch(self, events: list[RawActivityEvent]) -> None:
        """Ingest a batch of raw activity events into buffer."""
        for ev in events:
            self.ingest_event(ev)

    def flush_micro_window(
        self,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> MicroActivitySlice:
        """Process buffered raw events into a 10-minute micro slice (zero LLM token cost)."""
        now = datetime.now(UTC)
        end = window_end or now
        start = window_start or (end - timedelta(minutes=self.config.micro_window_minutes))

        events_to_fold = list(self._raw_event_buffer)
        self._raw_event_buffer.clear()

        slice_obj = self.micro_folder.fold_window(
            events=events_to_fold,
            window_start=start,
            window_end=end,
        )
        self._micro_slices.append(slice_obj)
        return slice_obj

    def distill_macro_window(
        self,
        window_start: datetime | None = None,
        window_end: datetime | None = None,
    ) -> MacroMilestoneFold:
        """Distill buffered micro slices into a 6-hour macro milestone fold."""
        now = datetime.now(UTC)
        end = window_end or now
        start = window_start or (end - timedelta(hours=self.config.macro_window_hours))

        # Select micro slices belonging to this macro window
        relevant_slices = [
            s for s in self._micro_slices if start <= s.start_time <= end
        ]

        macro_fold = self.macro_distiller.distill_window(
            slices=relevant_slices,
            window_start=start,
            window_end=end,
        )
        self._macro_folds.append(macro_fold)
        return macro_fold

    # Aliases for explicit triggering
    trigger_micro_fold = flush_micro_window
    trigger_macro_distill = distill_macro_window

    @property
    def micro_slices(self) -> list[MicroActivitySlice]:
        """Return all recorded micro activity slices."""
        return list(self._micro_slices)

    @property
    def macro_folds(self) -> list[MacroMilestoneFold]:
        """Return all recorded macro milestone folds."""
        return list(self._macro_folds)

    def synthesize_daily_archive(self, date_str: str | None = None) -> DailyPreferenceArchive:
        """Synthesize daily facts and long-term user preferences from all macro folds."""
        target_date = date_str or datetime.now(UTC).strftime("%Y-%m-%d")
        archive_id = f"daily_{uuid.uuid4().hex[:8]}"

        # Consolidate facts from macro folds
        facts: list[str] = []
        preferences: list[str] = []

        for fold in self._macro_folds:
            if fold.milestone_summary and fold.milestone_summary not in facts:
                facts.append(fold.milestone_summary)
            for act in fold.key_activities:
                if act not in facts:
                    facts.append(act)

            if "development" in fold.tags:
                preferences.append("偏好使用专业代码编辑器与本地终端环境进行开发")
            if "testing" in fold.tags:
                preferences.append("重视自动化测试与验证质量门禁")

        dedup_prefs = list(dict.fromkeys(preferences))

        archive = DailyPreferenceArchive(
            archive_id=archive_id,
            date_str=target_date,
            consolidated_facts=facts,
            preference_updates=dedup_prefs,
            total_raw_events_processed=self._total_raw_events_count,
            macro_folds_count=len(self._macro_folds),
        )
        self._daily_archives.append(archive)
        return archive

    def get_telemetry(self) -> CompactorPipelineTelemetry:
        """Calculate pipeline telemetry and estimated LLM tokens saved via folding."""
        total_raw = self._total_raw_events_count
        total_micro = len(self._micro_slices)
        total_macro = len(self._macro_folds)

        # If every event had triggered an LLM call: ~150 tokens per raw event
        # With folding: only macro folds trigger LLM distillation (~500 tokens each)
        raw_token_potential = total_raw * 150
        actual_macro_tokens = total_macro * 500
        tokens_saved = max(0, raw_token_potential - actual_macro_tokens)

        distilled_count = total_micro + total_macro
        compression_ratio = round(total_raw / distilled_count, 2) if distilled_count > 0 else 0.0

        return CompactorPipelineTelemetry(
            total_raw_events=total_raw,
            total_micro_slices=total_micro,
            total_macro_folds=total_macro,
            idle_events_dropped=self._idle_events_dropped_count,
            estimated_tokens_saved=tokens_saved,
            compression_ratio=compression_ratio,
        )

    def get_micro_slices(self, limit: int = 50) -> list[MicroActivitySlice]:
        """Return recent micro activity slices."""
        return list(self._micro_slices[-limit:])

    def get_macro_folds(self, limit: int = 20) -> list[MacroMilestoneFold]:
        """Return recent macro milestone folds."""
        return list(self._macro_folds[-limit:])

    def reset(self) -> None:
        """Reset internal buffers and history stores."""
        self._raw_event_buffer.clear()
        self._micro_slices.clear()
        self._macro_folds.clear()
        self._daily_archives.clear()
        self._total_raw_events_count = 0
        self._idle_events_dropped_count = 0
