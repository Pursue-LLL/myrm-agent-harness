"""[POS]: tests/unit/toolkits/memory/test_activity_compactor_suite.py
[INPUT]: None.
[OUTPUT]: Comprehensive unit tests for hierarchical time-window activity compactor pipeline.
"""

from datetime import UTC, datetime, timedelta

from myrm_agent_harness.toolkits.memory import (
    ActivityActionType,
    CompactorPipelineConfig,
    HierarchicalActivityCompactorPipeline,
    MacroMilestoneDistiller,
    MicroActivityFolder,
    RawActivityEvent,
)


def test_micro_activity_folder_debouncing_and_clustering() -> None:
    """Verify 10-minute micro folder debounces high-frequency events and clusters active windows."""
    folder = MicroActivityFolder(idle_threshold_seconds=120.0)
    base_time = datetime(2026, 10, 8, 10, 0, 0, tzinfo=UTC)

    # 1. Empty events window -> idle silence slice
    empty_slice = folder.fold_window([], base_time, base_time + timedelta(minutes=10))
    assert empty_slice.is_idle is True
    assert empty_slice.raw_event_count == 0
    assert "静默段" in empty_slice.folded_summary

    # 2. Burst of events in VSCode and Terminal
    events: list[RawActivityEvent] = [
        RawActivityEvent(
            event_id="ev_01",
            timestamp=base_time + timedelta(seconds=10),
            app_name="VSCode",
            window_title="server.py - myrm-agent",
            action_type=ActivityActionType.WINDOW_FOCUS,
        ),
        RawActivityEvent(
            event_id="ev_02",
            timestamp=base_time + timedelta(seconds=30),
            app_name="VSCode",
            window_title="server.py - myrm-agent",
            action_type=ActivityActionType.KEYSTROKE_BURST,
            event_payload="def test_something(): ...",
        ),
        RawActivityEvent(
            event_id="ev_03",
            timestamp=base_time + timedelta(seconds=60),
            app_name="Terminal",
            window_title="zsh - bash",
            action_type=ActivityActionType.TERMINAL_CMD,
            event_payload="pytest tests/unit/test_server.py",
        ),
        RawActivityEvent(
            event_id="ev_04",
            timestamp=base_time + timedelta(seconds=90),
            app_name="VSCode",
            window_title="test_server.py - myrm-agent",
            action_type=ActivityActionType.WINDOW_FOCUS,
        ),
    ]

    folded = folder.fold_window(events, base_time, base_time + timedelta(minutes=10))
    assert folded.is_idle is False
    assert folded.raw_event_count == 4
    assert folded.primary_app == "VSCode"
    assert len(folded.unique_windows) >= 2
    assert "server.py - myrm-agent" in folded.unique_windows
    assert folded.active_minutes > 0.0
    assert "VSCode" in folded.folded_summary


def test_macro_milestone_distiller_aggregation() -> None:
    """Verify 6-hour macro distiller aggregates micro slices and produces tags and summaries."""
    distiller = MacroMilestoneDistiller()
    base_time = datetime(2026, 10, 8, 8, 0, 0, tzinfo=UTC)

    folder = MicroActivityFolder()
    # Create two micro slices
    ev1 = [
        RawActivityEvent(
            event_id="e1",
            timestamp=base_time + timedelta(minutes=5),
            app_name="PyCharm",
            window_title="models.py",
            action_type=ActivityActionType.WINDOW_FOCUS,
        ),
        RawActivityEvent(
            event_id="e2",
            timestamp=base_time + timedelta(minutes=7),
            app_name="Terminal",
            window_title="zsh",
            action_type=ActivityActionType.TERMINAL_CMD,
            event_payload="pytest tests/unit",
        ),
    ]
    slice1 = folder.fold_window(ev1, base_time, base_time + timedelta(minutes=10))

    ev2 = [
        RawActivityEvent(
            event_id="e3",
            timestamp=base_time + timedelta(minutes=25),
            app_name="Google Chrome",
            window_title="FastAPI Documentation - Web",
            action_type=ActivityActionType.BROWSER_NAV,
            event_payload="https://fastapi.tiangolo.com",
        )
    ]
    slice2 = folder.fold_window(ev2, base_time + timedelta(minutes=20), base_time + timedelta(minutes=30))

    macro_fold = distiller.distill_window(
        [slice1, slice2],
        base_time,
        base_time + timedelta(hours=6),
    )

    assert macro_fold.micro_slices_count == 2
    assert "development" in macro_fold.tags or "testing" in macro_fold.tags or "research" in macro_fold.tags
    assert len(macro_fold.key_activities) >= 1
    assert macro_fold.confidence >= 0.85
    assert "持续工作约" in macro_fold.milestone_summary


def test_hierarchical_activity_compactor_pipeline_lifecycle() -> None:
    """Verify end-to-end pipeline ingestion, micro-flush, macro-distillation, and telemetry."""
    config = CompactorPipelineConfig(micro_window_minutes=10, macro_window_hours=6)
    pipeline = HierarchicalActivityCompactorPipeline(config=config)

    now = datetime.now(UTC)

    # 1. Ingest raw events
    pipeline.ingest_batch(
        [
            RawActivityEvent(
                event_id="e_01",
                timestamp=now - timedelta(minutes=8),
                app_name="VSCode",
                window_title="main.ts",
                action_type=ActivityActionType.WINDOW_FOCUS,
            ),
            RawActivityEvent(
                event_id="e_02",
                timestamp=now - timedelta(minutes=5),
                app_name="VSCode",
                window_title="main.ts",
                action_type=ActivityActionType.KEYSTROKE_BURST,
            ),
            RawActivityEvent(
                event_id="e_03",
                timestamp=now - timedelta(minutes=2),
                app_name="System",
                window_title="Desktop",
                action_type=ActivityActionType.IDLE_SILENCE,
            ),
        ]
    )

    # 2. Flush micro window
    slice_res = pipeline.flush_micro_window()
    assert slice_res.raw_event_count == 3
    assert len(pipeline.get_micro_slices()) == 1

    # 3. Distill macro window
    macro_res = pipeline.distill_macro_window()
    assert macro_res.micro_slices_count == 1
    assert len(pipeline.get_macro_folds()) == 1

    # 4. Synthesize daily archive
    archive = pipeline.synthesize_daily_archive(date_str="2026-10-08")
    assert archive.date_str == "2026-10-08"
    assert archive.total_raw_events_processed == 3
    assert archive.macro_folds_count == 1

    # 5. Check Telemetry
    telemetry = pipeline.get_telemetry()
    assert telemetry.total_raw_events == 3
    assert telemetry.total_micro_slices == 1
    assert telemetry.total_macro_folds == 1
    assert telemetry.idle_events_dropped == 1
    assert telemetry.compression_ratio > 0.0
