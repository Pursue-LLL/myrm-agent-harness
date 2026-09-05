"""Unit tests for TimezoneExplicitOffset and LocaleStability strategies.

Ensures deterministic timezone resolution, DST (Daylight Saving Time) awareness,
and locale anchor preservation in memory candidates.
"""

from __future__ import annotations

from datetime import datetime, timezone

from myrm_agent_harness.toolkits.memory.strategies.behavioral_measurement import (
    BehavioralMessage,
    BehavioralStatsOptions,
    compute_routine_measurement,
    resolve_utc_offset_minutes,
)


def test_resolve_utc_offset_minutes_iana_standard() -> None:
    # Shanghai is UTC+8 (+480 minutes) year-round
    dt = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)
    offset = resolve_utc_offset_minutes("Asia/Shanghai", dt)
    assert offset == 480


def test_resolve_utc_offset_minutes_dst_summer_vs_winter() -> None:
    # New York in Summer (EDT) is UTC-4 (-240 minutes)
    summer_dt = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    summer_offset = resolve_utc_offset_minutes("America/New_York", summer_dt)
    assert summer_offset == -240

    # New York in Winter (EST) is UTC-5 (-300 minutes)
    winter_dt = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    winter_offset = resolve_utc_offset_minutes("America/New_York", winter_dt)
    assert winter_offset == -300


def test_resolve_utc_offset_minutes_fixed_offsets() -> None:
    assert resolve_utc_offset_minutes("+08:00") == 480
    assert resolve_utc_offset_minutes("-05:00") == -300
    assert resolve_utc_offset_minutes("UTC") == 0
    assert resolve_utc_offset_minutes("Z") == 0


def test_resolve_utc_offset_minutes_fallback_on_invalid() -> None:
    # Graceful fallback to default UTC (0) on corrupted or empty input
    assert resolve_utc_offset_minutes(None) == 0
    assert resolve_utc_offset_minutes("") == 0
    assert resolve_utc_offset_minutes("Invalid/Non_Existent_Timezone_123") == 0


def test_compute_routine_measurement_with_iana_resolved_messages() -> None:
    # User sends a message at 14:00 UTC, which was 10:00 AM EDT in New York (summer: UTC-4)
    ref_dt = datetime(2026, 7, 1, 14, 0, tzinfo=timezone.utc)
    offset = resolve_utc_offset_minutes("America/New_York", ref_dt)
    assert offset == -240

    msg = BehavioralMessage(
        id="msg_1",
        chat_id="chat_1",
        channel="web",
        sender_id="user_alice",
        sender_name="Alice",
        created_at_ms=int(ref_dt.timestamp() * 1000),
        offset_minutes=offset,
        is_self=True,
    )

    measurement = compute_routine_measurement(
        [msg],
        options=BehavioralStatsOptions(min_self_messages=1),
    )

    # 14:00 UTC + (-240 min) = 10:00 local time
    # 2026-07-01 is Wednesday (workday)
    assert measurement.workday_hour_histogram[10] == 1
    assert measurement.workday_hour_histogram[14] == 0


def test_distillation_candidate_locale_anchor_default() -> None:
    from myrm_agent_harness.toolkits.memory.strategies.distillation_guards import DistillationCandidate
    c = DistillationCandidate(content="Hello world", target_locale="zh")
    assert c.target_locale == "zh"

