"""Unit tests for desktop long-session eviction and memory watchdog suite.

Verifies:
- Turn dehydration, rich media stripping, and memory compression ratios.
- On-demand turn rehydration from backing cache.
- Sliding viewport history dehydration (preserving recent active turns).
- Cross-platform RSS extraction and user idle period detection.
- Multi-tier memory pressure evaluation (NORMAL, WARNING, CRITICAL, EMERGENCY).
- User-idle gated compaction vs. forced critical garbage collection.
- Rolling session archive partitioning and milestone summary synthesis.
"""

from __future__ import annotations

import time

import pytest

from myrm_agent_harness.runtime.survival import (
    DehydratedSessionTurn,
    DesktopMemoryWatchdog,
    LongSessionRollingArchiver,
    SessionContextDehydrator,
    SessionTurn,
    get_current_rss_bytes,
)


@pytest.mark.asyncio
async def test_turn_dehydration_and_on_demand_rehydration() -> None:
    dehydrator = SessionContextDehydrator(max_cached_raw_turns=10)

    heavy_media = {
        "echarts_option": {"series": [{"data": list(range(1000))}]},
        "monaco_diff": "diff --git a/big.py b/big.py\n" + ("+line\n" * 500),
    }

    turn = SessionTurn(
        turn_id="turn-001",
        session_id="sess-abc",
        turn_index=1,
        user_query="Analyze system logs and generate chart",
        agent_response="Generated comprehensive system analytics chart successfully.",
        rich_media=heavy_media,
    )

    dehydrated = await dehydrator.dehydrate_turn(turn)
    assert dehydrated.turn_id == "turn-001"
    assert dehydrated.state == "DEHYDRATED"
    assert dehydrated.rich_media_count == 2
    # Memory size must be heavily compacted
    assert dehydrated.dehydrated_estimated_bytes < dehydrated.original_estimated_bytes
    assert dehydrator.cached_turns_count == 1

    # On-demand rehydration
    restored = await dehydrator.rehydrate_turn("turn-001")
    assert restored is not None
    assert restored.turn_id == "turn-001"
    assert restored.rich_media == heavy_media


@pytest.mark.asyncio
async def test_sliding_viewport_history_dehydration() -> None:
    dehydrator = SessionContextDehydrator()

    turns: list[SessionTurn] = [
        SessionTurn(
            turn_id=f"turn-{i}",
            session_id="sess-xyz",
            turn_index=i,
            user_query=f"Query {i}",
            agent_response=f"Response {i}",
            rich_media={"data": f"content-{i}"},
        )
        for i in range(1, 16)
    ]

    # Keep only the most recent 5 turns hydrated; dehydrate older 10 turns
    results = await dehydrator.dehydrate_session_history(turns, keep_recent=5)
    assert len(results) == 15

    # First 10 turns must be DehydratedSessionTurn
    for item in results[:10]:
        assert isinstance(item, DehydratedSessionTurn)
        assert item.state == "DEHYDRATED"

    # Last 5 turns must remain original SessionTurn
    for item in results[10:]:
        assert not hasattr(item, "state")
        assert isinstance(item, SessionTurn)

    # Cache clear
    cleared = await dehydrator.clear_cache()
    assert cleared == 10
    assert dehydrator.cached_turns_count == 0


def test_rss_extraction_and_idle_detection() -> None:
    rss = get_current_rss_bytes()
    assert rss > 0

    watchdog = DesktopMemoryWatchdog(idle_threshold_seconds=0.2)
    now = time.time()

    # Right after user activity, not idle
    watchdog.mark_user_activity(now)
    assert not watchdog.is_idle(now=now)

    # After threshold expires, becomes idle
    assert watchdog.is_idle(now=now + 0.3)


def test_memory_pressure_evaluation_tiers() -> None:
    watchdog = DesktopMemoryWatchdog(
        warning_rss_bytes=1000,
        critical_rss_bytes=2000,
        emergency_rss_bytes=3000,
    )

    assert watchdog.evaluate_memory_pressure(current_rss=500) == "NORMAL"
    assert watchdog.evaluate_memory_pressure(current_rss=1500) == "WARNING"
    assert watchdog.evaluate_memory_pressure(current_rss=2500) == "CRITICAL"
    assert watchdog.evaluate_memory_pressure(current_rss=3500) == "EMERGENCY"


@pytest.mark.asyncio
async def test_idle_gated_compaction_vs_forced_critical() -> None:
    dehydrator = SessionContextDehydrator()
    watchdog = DesktopMemoryWatchdog(dehydrator=dehydrator, idle_threshold_seconds=10.0)

    turn = SessionTurn(
        turn_id="turn-trim-1",
        session_id="sess-trim",
        turn_index=1,
        user_query="Query",
        agent_response="Response",
    )
    await dehydrator.dehydrate_turn(turn)
    assert dehydrator.cached_turns_count == 1

    # 1. Under WARNING, user actively interacting -> Compaction is suppressed
    watchdog.mark_user_activity()
    receipt_suppressed = await watchdog.trigger_compaction(
        level="WARNING",
        force=False,
        simulated_pre_rss=1500,
        simulated_post_rss=1500,
    )
    assert receipt_suppressed.freed_bytes == 0
    assert dehydrator.cached_turns_count == 1

    # 2. Under CRITICAL, compaction runs immediately even if user is active
    receipt_critical = await watchdog.trigger_compaction(
        level="CRITICAL",
        force=False,
        simulated_pre_rss=2500,
        simulated_post_rss=1200,
    )
    assert receipt_critical.level == "CRITICAL"
    assert receipt_critical.freed_bytes == 1300
    assert receipt_critical.dehydrated_turns_count == 1
    assert dehydrator.cached_turns_count == 0


@pytest.mark.asyncio
async def test_rolling_archive_partitioning_and_milestones() -> None:
    archiver = LongSessionRollingArchiver(
        max_turns_per_volume=10,
        trigger_threshold=15,
    )

    turns = [
        SessionTurn(
            turn_id=f"turn-{i}",
            session_id="session-long",
            turn_index=i,
            user_query=f"Goal step {i}",
            agent_response=f"Completed sub-goal {i}",
        )
        for i in range(1, 20)
    ]

    # Turns (19) exceed threshold (15) -> Generates volume with first 10 turns
    vol, remaining = await archiver.maybe_archive_session("session-long", turns)
    assert vol is not None
    assert vol.session_id == "session-long"
    assert vol.volume_index == 1
    assert vol.start_turn_index == 1
    assert vol.end_turn_index == 10
    assert vol.retained_turns_count == 10
    assert "Milestone Archive: 10 historical turns archived" in vol.milestone_summary
    assert len(remaining) == 9
    assert remaining[0].turn_index == 11

    # Query volumes
    volumes_list = await archiver.list_volumes("session-long")
    assert len(volumes_list) == 1
    assert volumes_list[0].volume_id == vol.volume_id

    fetched_vol = await archiver.get_volume(vol.volume_id)
    assert fetched_vol is not None
    assert fetched_vol.volume_id == vol.volume_id

    # Secondary evaluation with remaining 9 turns does not trigger
    vol2, remaining2 = await archiver.maybe_archive_session("session-long", remaining)
    assert vol2 is None
    assert len(remaining2) == 9
