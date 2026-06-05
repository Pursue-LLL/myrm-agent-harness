"""Engine for calculating free/busy time overlaps and finding optimal meeting slots.

Uses a sweep-line algorithm to merge overlapping busy intervals and
extract free time slots within a given working hours range.

[INPUT]
- (none)

[OUTPUT]
- FreeBusyEngine: Engine class for free/busy calculations.
- TimeSlot: Data class representing a start and end datetime.

[POS]
Engine for calculating free/busy time overlaps.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class TimeSlot:
    """Represents a time interval with a start and end."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        if self.start >= self.end:
            raise ValueError(f"Invalid TimeSlot: start {self.start} must be before end {self.end}")


class FreeBusyEngine:
    """Engine for processing free/busy slots."""

    @staticmethod
    def merge_busy_slots(slots: Sequence[TimeSlot]) -> list[TimeSlot]:
        """Merge overlapping or adjacent busy slots using a sweep-line approach.

        Args:
            slots: Unsorted, potentially overlapping busy time slots.

        Returns:
            Sorted, merged busy time slots.
        """
        if not slots:
            return []

        # Sort slots by start time
        sorted_slots = sorted(slots, key=lambda s: s.start)
        merged: list[TimeSlot] = []

        current_start = sorted_slots[0].start
        current_end = sorted_slots[0].end

        for slot in sorted_slots[1:]:
            if slot.start <= current_end:
                # Overlapping or adjacent, extend the current end if necessary
                if slot.end > current_end:
                    current_end = slot.end
            else:
                # No overlap, push the current merged slot and start a new one
                merged.append(TimeSlot(start=current_start, end=current_end))
                current_start = slot.start
                current_end = slot.end

        # Append the last merged slot
        merged.append(TimeSlot(start=current_start, end=current_end))
        return merged

    @staticmethod
    def find_free_slots(
        busy_slots: Sequence[TimeSlot],
        search_start: datetime,
        search_end: datetime,
        duration_minutes: int,
        working_hours_start: int = 9,
        working_hours_end: int = 18,
    ) -> list[TimeSlot]:
        """Find available free time slots given a list of merged busy slots.

        Args:
            busy_slots: Merged busy time slots.
            search_start: The start of the overall search window.
            search_end: The end of the overall search window.
            duration_minutes: The required minimum duration of a free slot.
            working_hours_start: Hour of day when working hours start (0-23).
            working_hours_end: Hour of day when working hours end (0-23).

        Returns:
            List of available free time slots.
        """
        if search_start >= search_end:
            return []

        # We need to intersect the available time with the working hours of each day
        free_slots: list[TimeSlot] = []
        duration = timedelta(minutes=duration_minutes)
        merged_busy = FreeBusyEngine.merge_busy_slots(busy_slots)

        current_time = search_start

        while current_time < search_end:
            # Determine working hours for the current day
            work_start_today = datetime(
                current_time.year,
                current_time.month,
                current_time.day,
                working_hours_start,
                0,
                0,
                tzinfo=current_time.tzinfo,
            )
            work_end_today = datetime(
                current_time.year,
                current_time.month,
                current_time.day,
                working_hours_end,
                0,
                0,
                tzinfo=current_time.tzinfo,
            )

            # Skip weekends (Saturday=5, Sunday=6)
            if current_time.weekday() >= 5:
                current_time = work_start_today + timedelta(days=1)
                continue

            # Ensure we are within working hours
            slot_start = max(current_time, work_start_today)
            slot_end = min(search_end, work_end_today)

            if slot_start < slot_end:
                # Find all busy slots that overlap with this working window
                overlapping_busy = [b for b in merged_busy if b.start < slot_end and b.end > slot_start]

                window_start = slot_start
                for busy in overlapping_busy:
                    # If there is enough gap before the busy slot, add it
                    if busy.start - window_start >= duration:
                        free_slots.append(TimeSlot(start=window_start, end=busy.start))
                    # Move the window start past the busy slot
                    window_start = max(window_start, busy.end)

                # Check the gap after the last busy slot within the working window
                if slot_end - window_start >= duration:
                    free_slots.append(TimeSlot(start=window_start, end=slot_end))

            # Move to the start of the next day
            current_time = work_start_today + timedelta(days=1)

        return free_slots
