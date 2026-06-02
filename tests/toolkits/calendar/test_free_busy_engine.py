"""Tests for FreeBusyEngine."""

from datetime import UTC, datetime, timedelta

import pytest

from myrm_agent_harness.toolkits.calendar.free_busy_engine import FreeBusyEngine, TimeSlot


def test_merge_busy_slots():
    # Setup overlapping and adjacent slots
    base = datetime(2026, 5, 20, 9, 0, tzinfo=UTC)
    slots = [
        TimeSlot(start=base, end=base + timedelta(hours=2)),          # 09:00 - 11:00
        TimeSlot(start=base + timedelta(hours=1), end=base + timedelta(hours=3)), # 10:00 - 12:00
        TimeSlot(start=base + timedelta(hours=4), end=base + timedelta(hours=5)), # 13:00 - 14:00
    ]

    merged = FreeBusyEngine.merge_busy_slots(slots)

    assert len(merged) == 2
    assert merged[0].start == base
    assert merged[0].end == base + timedelta(hours=3) # 09:00 - 12:00
    assert merged[1].start == base + timedelta(hours=4)
    assert merged[1].end == base + timedelta(hours=5)

def test_find_free_slots():
    # Setup search window
    search_start = datetime(2026, 5, 20, 8, 0, tzinfo=UTC) # Wed
    search_end = datetime(2026, 5, 20, 18, 0, tzinfo=UTC)

    # 09:00 - 12:00 busy, 14:00 - 15:00 busy
    base = datetime(2026, 5, 20, 9, 0, tzinfo=UTC)
    busy_slots = [
        TimeSlot(start=base, end=base + timedelta(hours=3)),
        TimeSlot(start=base + timedelta(hours=5), end=base + timedelta(hours=6)),
    ]

    # Duration 60 mins. Working hours 9-18
    free_slots = FreeBusyEngine.find_free_slots(
        busy_slots,
        search_start=search_start,
        search_end=search_end,
        duration_minutes=60,
        working_hours_start=9,
        working_hours_end=18
    )

    # Expected free slots:
    # 12:00 - 14:00
    # 15:00 - 18:00
    assert len(free_slots) == 2
    assert free_slots[0].start == base + timedelta(hours=3)
    assert free_slots[0].end == base + timedelta(hours=5)

    assert free_slots[1].start == base + timedelta(hours=6)
    assert free_slots[1].end == datetime(2026, 5, 20, 18, 0, tzinfo=UTC)

def test_invalid_timeslot():
    base = datetime(2026, 5, 20, 9, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        TimeSlot(start=base, end=base - timedelta(hours=1))
