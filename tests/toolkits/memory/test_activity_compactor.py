"""Unit tests for Hierarchical Time-Window Activity Compactor pipeline suite."""

from datetime import UTC, datetime, timedelta

from myrm_agent_harness.toolkits.memory.activity_compactor import (
    ActivityActionType,
    CompactorPipelineConfig,
    HierarchicalActivityCompactorPipeline,
    MacroMilestoneDistiller,
    MicroActivityFolder,
    RawActivityEvent,
)


def test_micro_activity_folder_debouncing_and_clustering():
    """Verify that 10-minute raw event bursts are algorithmically folded without LLM calls."""
    folder = MicroActivityFolder(idle_threshold_seconds=120.0)
    base_time = datetime.now(UTC)

    # 1. Test empty / idle silence
    empty_slice = folder.fold_window(
        events=[],
        window_start=base_time,
        window_end=base_time + timedelta(minutes=10),
    )
    assert empty_slice.is_idle is True
    assert empty_slice.raw_event_count == 0
    assert "无用户活跃操作" in empty_slice.folded_summary

    # 2. Test high-frequency activity stream (20 events)
    events: list[RawActivityEvent] = []
    for i in range(15):
        events.append(
            RawActivityEvent(
                event_id=f"ev_{i}",
                timestamp=base_time + timedelta(seconds=i * 20),
                app_name="VSCode",
                window_title="src/services/api.ts - myrm-agent",
                action_type=ActivityActionType.KEYSTROKE_BURST,
                event_payload="editing code",
            )
        )

    # Add terminal executions
    events.append(
        RawActivityEvent(
            event_id="ev_term_1",
            timestamp=base_time + timedelta(seconds=320),
            app_name="Terminal",
            window_title="zsh - dev",
            action_type=ActivityActionType.TERMINAL_CMD,
            event_payload="bun test",
        )
    )
    events.append(
        RawActivityEvent(
            event_id="ev_term_2",
            timestamp=base_time + timedelta(seconds=340),
            app_name="Terminal",
            window_title="zsh - dev",
            action_type=ActivityActionType.TERMINAL_CMD,
            event_payload="git status",
        )
    )

    folded_slice = folder.fold_window(
        events=events,
        window_start=base_time,
        window_end=base_time + timedelta(minutes=10),
    )

    assert folded_slice.is_idle is False
    assert folded_slice.raw_event_count == 17
    assert folded_slice.primary_app == "VSCode"
    assert "VSCode" in folded_slice.folded_summary
    assert "bun test" in folded_slice.folded_summary
    assert folded_slice.active_minutes > 0.0
    assert len(folded_slice.unique_windows) >= 1


def test_macro_milestone_distiller_aggregation():
    """Verify distilling sequences of micro slices into a 6-hour macro milestone fold."""
    distiller = MacroMilestoneDistiller()
    base_time = datetime.now(UTC)

    folder = MicroActivityFolder()
    slice_1 = folder.fold_window(
        events=[
            RawActivityEvent(
                event_id="e1",
                timestamp=base_time,
                app_name="VSCode",
                window_title="auth.ts",
                action_type=ActivityActionType.KEYSTROKE_BURST,
            )
        ],
        window_start=base_time,
        window_end=base_time + timedelta(minutes=10),
    )
    slice_2 = folder.fold_window(
        events=[
            RawActivityEvent(
                event_id="e2",
                timestamp=base_time + timedelta(minutes=15),
                app_name="Terminal",
                window_title="bash",
                action_type=ActivityActionType.TERMINAL_CMD,
                event_payload="pytest tests/unit",
            )
        ],
        window_start=base_time + timedelta(minutes=10),
        window_end=base_time + timedelta(minutes=20),
    )
    slice_idle = folder.fold_window(
        events=[],
        window_start=base_time + timedelta(minutes=20),
        window_end=base_time + timedelta(minutes=30),
    )

    macro_fold = distiller.distill_window(
        slices=[slice_1, slice_2, slice_idle],
        window_start=base_time,
        window_end=base_time + timedelta(hours=6),
    )

    assert macro_fold.micro_slices_count == 3
    assert "development" in macro_fold.tags
    assert "testing" in macro_fold.tags
    assert len(macro_fold.key_activities) == 2
    assert "VSCode" in macro_fold.milestone_summary


def test_hierarchical_activity_compactor_pipeline_lifecycle():
    """Verify end-to-end pipeline streaming ingestion, folding, archiving, and telemetry."""
    config = CompactorPipelineConfig(
        micro_window_minutes=10,
        macro_window_hours=6,
        idle_threshold_seconds=60.0,
        max_raw_buffer_size=100,
    )
    pipeline = HierarchicalActivityCompactorPipeline(config=config)
    now = datetime.now(UTC)

    # 1. Stream ingest raw events
    for i in range(25):
        pipeline.ingest_event(
            RawActivityEvent(
                event_id=f"evt_{i}",
                timestamp=now + timedelta(seconds=i * 10),
                app_name="Chrome" if i % 2 == 0 else "VSCode",
                window_title="Pull Request #42" if i % 2 == 0 else "main.py",
                action_type=ActivityActionType.BROWSER_NAV if i % 2 == 0 else ActivityActionType.KEYSTROKE_BURST,
            )
        )

    # Ingest 2 idle events
    pipeline.ingest_event(
        RawActivityEvent(
            event_id="idle_1",
            timestamp=now + timedelta(seconds=260),
            app_name="System",
            window_title="LockScreen",
            action_type=ActivityActionType.IDLE_SILENCE,
        )
    )

    # 2. Trigger micro fold
    micro_slice = pipeline.trigger_micro_fold()
    assert micro_slice.raw_event_count == 26
    assert len(pipeline.micro_slices) == 1

    # 3. Trigger macro distill
    macro_fold = pipeline.trigger_macro_distill()
    assert macro_fold.micro_slices_count == 1
    assert len(pipeline.macro_folds) == 1

    # 4. Synthesize daily archive
    archive = pipeline.synthesize_daily_archive(date_str="2026-10-08")
    assert archive.date_str == "2026-10-08"
    assert archive.total_raw_events_processed == 26
    assert archive.macro_folds_count == 1
    assert len(archive.consolidated_facts) >= 1

    # 5. Check telemetry
    telemetry = pipeline.get_telemetry()
    assert telemetry.total_raw_events == 26
    assert telemetry.total_micro_slices == 1
    assert telemetry.total_macro_folds == 1
    assert telemetry.idle_events_dropped == 1
    assert telemetry.estimated_tokens_saved > 0
    assert telemetry.compression_ratio == 13.0
