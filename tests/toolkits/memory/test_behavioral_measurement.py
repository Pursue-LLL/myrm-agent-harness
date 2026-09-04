"""Unit tests for zero-model-cost deterministic behavioral measurement strategy."""

from datetime import UTC, datetime, timedelta
import json

import pytest

from myrm_agent_harness.toolkits.memory.strategies.behavioral_measurement import (
    BehavioralMessage,
    BehavioralStatsOptions,
    RoutineMeasurement,
    _local_hour_and_weekday,
    _resolve_peak_window,
    compute_routine_measurement,
    generate_behavioral_profile_candidates,
    percentile,
)
from myrm_agent_harness.toolkits.memory.types import MemoryType


class TestPercentileNearestRank:
    def test_empty_list_returns_none(self) -> None:
        assert percentile([], 0.5) is None

    def test_single_element(self) -> None:
        assert percentile([42.0], 0.5) == 42.0
        assert percentile([42.0], 0.0) == 42.0
        assert percentile([42.0], 1.0) == 42.0

    def test_multi_element_nearest_rank(self) -> None:
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        assert percentile(values, 0.0) == 10.0
        assert percentile(values, 0.5) == 30.0
        assert percentile(values, 1.0) == 50.0

    def test_clamped_out_of_bounds(self) -> None:
        values = [5.0, 15.0]
        assert percentile(values, -0.5) == 5.0
        assert percentile(values, 1.5) == 15.0


class TestTimezoneLocalShift:
    def test_utc_to_beijing_shift(self) -> None:
        # 2026-09-04 04:00:00 UTC -> 12:00:00 UTC+8 (Friday, weekday=4)
        base_dt = datetime(2026, 9, 4, 4, 0, 0, tzinfo=UTC)
        ms = int(base_dt.timestamp() * 1000)
        hour, weekday = _local_hour_and_weekday(ms, offset_minutes=480)
        assert hour == 12
        assert weekday == 4

    def test_utc_to_new_york_shift(self) -> None:
        # 2026-09-04 02:00:00 UTC -> 2026-09-03 22:00:00 UTC-4 (Thursday, weekday=3)
        base_dt = datetime(2026, 9, 4, 2, 0, 0, tzinfo=UTC)
        ms = int(base_dt.timestamp() * 1000)
        hour, weekday = _local_hour_and_weekday(ms, offset_minutes=-240)
        assert hour == 22
        assert weekday == 3


class TestPeakWindowResolution:
    def test_peak_window_identified(self) -> None:
        # 24 hours histogram with 40 events, 30 of which fall in 14:00 - 17:00 (hours 14, 15, 16, 17)
        hist = [0] * 24
        hist[14] = 8
        hist[15] = 10
        hist[16] = 7
        hist[17] = 5
        window = _resolve_peak_window(hist, min_count=20)
        assert window == "14:00 - 18:00"

    def test_flat_distribution_returns_none(self) -> None:
        # Uniformly distributed 24 events (1 event per hour) -> no 4-hour window holds >= 30%
        hist = [1] * 24
        window = _resolve_peak_window(hist, min_count=20)
        assert window is None


class TestComputeRoutineMeasurement:
    def test_latency_calculation_strict_pairing(self) -> None:
        base_time = datetime(2026, 9, 4, 6, 0, 0, tzinfo=UTC)
        t0 = int(base_time.timestamp() * 1000)

        messages = [
            # Chat 1
            BehavioralMessage(
                id="msg_1",
                chat_id="chat_a",
                channel="feishu",
                sender_id="colleague",
                is_self=False,
                created_at_ms=t0,
                content="Hey there",
            ),
            # Self reply 30s later -> Valid latency: 30,000ms
            BehavioralMessage(
                id="msg_2",
                chat_id="chat_a",
                channel="feishu",
                sender_id="user_me",
                is_self=True,
                created_at_ms=t0 + 30_000,
                content="Hi! I'm here.",
            ),
            # Self sends another message 5s later -> Must NOT count as latency against oneself!
            BehavioralMessage(
                id="msg_3",
                chat_id="chat_a",
                channel="feishu",
                sender_id="user_me",
                is_self=True,
                created_at_ms=t0 + 35_000,
                content="Forgot to mention...",
            ),
            # Another speaker asks question
            BehavioralMessage(
                id="msg_4",
                chat_id="chat_a",
                channel="feishu",
                sender_id="colleague",
                is_self=False,
                created_at_ms=t0 + 60_000,
                content="Can you review this PR?",
            ),
            # Self reply 90s later -> Valid latency: 90,000ms
            BehavioralMessage(
                id="msg_5",
                chat_id="chat_a",
                channel="feishu",
                sender_id="user_me",
                is_self=True,
                created_at_ms=t0 + 150_000,
                content="Sure, looking now.",
            ),
        ]

        options = BehavioralStatsOptions(offset_minutes=480)
        measurement = compute_routine_measurement(messages, options)

        assert measurement.self_message_count == 3
        assert measurement.latency_sample_count == 2
        # P50 between 30,000 and 90,000
        assert measurement.reply_latency_p50_ms in (30000.0, 60000.0, 90000.0)
        assert measurement.reply_latency_p90_ms == 90000.0
        assert measurement.channel_distribution == {"feishu": 3}

    def test_idle_gap_cutoff_prevents_stale_latency_distortion(self) -> None:
        base_time = datetime(2026, 9, 1, 10, 0, 0, tzinfo=UTC)
        t0 = int(base_time.timestamp() * 1000)

        messages = [
            BehavioralMessage(
                id="m1",
                chat_id="c1",
                channel="webui",
                sender_id="other",
                is_self=False,
                created_at_ms=t0,
            ),
            # User replies 72 hours later (> 48h cutoff)
            BehavioralMessage(
                id="m2",
                chat_id="c1",
                channel="webui",
                sender_id="me",
                is_self=True,
                created_at_ms=t0 + 72 * 3600 * 1000,
            ),
        ]

        options = BehavioralStatsOptions(max_idle_gap_ms=48 * 3600 * 1000)
        measurement = compute_routine_measurement(messages, options)

        assert measurement.self_message_count == 1
        assert measurement.latency_sample_count == 0  # Dropped because gap exceeded cutoff
        assert measurement.reply_latency_p50_ms is None


class TestGenerateBehavioralProfileCandidates:
    def test_insufficient_samples_drops_candidates(self) -> None:
        base_time = datetime(2026, 9, 4, 10, 0, 0, tzinfo=UTC)
        t0 = int(base_time.timestamp() * 1000)

        # Only 5 self messages (below default threshold of 20)
        messages = [
            BehavioralMessage(
                id=f"msg_{i}",
                chat_id="c1",
                channel="webui",
                sender_id="me",
                is_self=True,
                created_at_ms=t0 + i * 1000,
            )
            for i in range(5)
        ]

        options = BehavioralStatsOptions(min_self_messages=20, min_latency_samples=10)
        candidates = generate_behavioral_profile_candidates(messages, options)
        # Should drop rather than producing noisy profile facts
        assert len(candidates) == 0

    def test_sufficient_samples_produces_profile_candidates(self) -> None:
        base_time = datetime(2026, 9, 4, 6, 0, 0, tzinfo=UTC)
        t0 = int(base_time.timestamp() * 1000)

        messages: list[BehavioralMessage] = []
        for i in range(25):
            # Interleaved other and self turns
            messages.append(
                BehavioralMessage(
                    id=f"other_{i}",
                    chat_id="c1",
                    channel="slack",
                    sender_id="teammate",
                    is_self=False,
                    created_at_ms=t0 + i * 60_000,
                )
            )
            messages.append(
                BehavioralMessage(
                    id=f"self_{i}",
                    chat_id="c1",
                    channel="slack",
                    sender_id="me",
                    is_self=True,
                    created_at_ms=t0 + i * 60_000 + 15_000,  # 15s latency
                    content=f"Response {i}",
                )
            )

        options = BehavioralStatsOptions(min_self_messages=20, min_latency_samples=10, offset_minutes=480)
        candidates = generate_behavioral_profile_candidates(messages, options)

        assert len(candidates) == 2
        keys = {c.profile_key for c in candidates}
        assert "routine_active_hours" in keys
        assert "routine_reply_latency" in keys

        for cand in candidates:
            assert cand.memory_type == MemoryType.PROFILE
            assert len(cand.evidence) > 0
            assert cand.confidence >= 0.50

        # Verify parsed payload
        latency_cand = next(c for c in candidates if c.profile_key == "routine_reply_latency")
        assert latency_cand.profile_value is not None
        lat_data = json.loads(latency_cand.profile_value)
        assert lat_data["p50_ms"] == 15000.0
        assert lat_data["sample_count"] == 25
