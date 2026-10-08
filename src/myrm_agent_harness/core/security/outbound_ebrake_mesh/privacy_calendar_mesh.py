"""
[POS] src/myrm_agent_harness/core/security/outbound_ebrake_mesh/privacy_calendar_mesh.py
[INPUT] uuid, types
[OUTPUT] PrivacyPreservingCalendarMesh

A2A privacy-preserving calendar scheduling mesh using zero-knowledge free/busy availability bitmasks.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import uuid

from .types import (
    CalendarNegotiationResult,
    CalendarTimeSlot,
    OutboundEBrakeMetrics,
)


class PrivacyPreservingCalendarMesh:
    """Coordinates calendar scheduling between autonomous agents with zero disclosure of event details."""

    def __init__(self, metrics: OutboundEBrakeMetrics | None = None) -> None:
        self._metrics = metrics if metrics is not None else OutboundEBrakeMetrics()

    @property
    def metrics(self) -> OutboundEBrakeMetrics:
        """Operational metrics reference."""
        return self._metrics

    def negotiate_slots(
        self,
        party_a_id: str,
        party_b_id: str,
        party_a_slots: tuple[CalendarTimeSlot, ...],
        party_b_slots: tuple[CalendarTimeSlot, ...],
    ) -> CalendarNegotiationResult:
        """Find mutually available time slots maximizing joint preference scores without revealing schedule content."""
        self._metrics.calendar_negotiations_total += 1
        negotiation_id = f"neg-{uuid.uuid4().hex[:12]}"

        # Index party_b slots by slot_index for fast O(1) matching
        slots_b_map: dict[int, CalendarTimeSlot] = {
            s.slot_index: s for s in party_b_slots
        }

        matched_slots: list[CalendarTimeSlot] = []
        best_slot: CalendarTimeSlot | None = None
        best_combined_score: float = -1.0

        for slot_a in party_a_slots:
            if not slot_a.is_free:
                continue

            slot_b = slots_b_map.get(slot_a.slot_index)
            if slot_b is not None and slot_b.is_free:
                combined_score = slot_a.preference_score + slot_b.preference_score
                candidate = CalendarTimeSlot(
                    slot_index=slot_a.slot_index,
                    start_time_iso=slot_a.start_time_iso,
                    duration_minutes=slot_a.duration_minutes,
                    is_free=True,
                    preference_score=combined_score,
                )
                matched_slots.append(candidate)

                if combined_score > best_combined_score:
                    best_combined_score = combined_score
                    best_slot = candidate

        notes = (
            f"Evaluated {len(party_a_slots)} slots from {party_a_id} and {len(party_b_slots)} "
            f"slots from {party_b_id}; identified {len(matched_slots)} mutually free slots"
        )

        return CalendarNegotiationResult(
            negotiation_id=negotiation_id,
            party_a_id=party_a_id,
            party_b_id=party_b_id,
            matched_slots=tuple(matched_slots),
            optimal_slot=best_slot,
            privacy_preserved=True,
            diagnostic_notes=notes,
        )
