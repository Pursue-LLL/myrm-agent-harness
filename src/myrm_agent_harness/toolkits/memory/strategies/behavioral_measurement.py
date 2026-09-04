"""Zero-model-cost deterministic behavioral measurement strategy.

Provides pure-local, zero-LLM statistical aggregation of user interaction routines,
including 24-hour active histograms, weekday distributions, response latency percentiles,
and channel activity distributions.

[INPUT]
- Sequence[BehavioralMessage]: Streamlined interaction message DTOs
- BehavioralStatsOptions: Explicit timezone offset and sample floor thresholds

[OUTPUT]
- RoutineMeasurement: Strong-typed numerical routine metrics
- generate_behavioral_profile_candidates: ExtractedMemory profile candidates with provenance

[POS]
Harness framework strategy layer. Pure Python standard library + Pydantic.
100% deterministic, zero network I/O, <2ms execution, fully decoupled from subjective LLM extraction.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
import json
import logging
from typing import Final

from pydantic import BaseModel, Field

from myrm_agent_harness.toolkits.memory.strategies.distillation_guards import EvidenceReference
from myrm_agent_harness.toolkits.memory.strategies.extractor import ExtractedMemory
from myrm_agent_harness.toolkits.memory.types import MemoryType

logger = logging.getLogger(__name__)

DEFAULT_MIN_SELF_MESSAGES: Final[int] = 20
DEFAULT_MIN_LATENCY_SAMPLES: Final[int] = 10
DEFAULT_MAX_IDLE_GAP_MS: Final[int] = 172_800_000  # 48 hours in milliseconds
DEFAULT_MAX_EVIDENCE: Final[int] = 20


class BehavioralMessage(BaseModel):
    """Normalized interaction message representation for deterministic measurement."""

    id: str
    chat_id: str
    channel: str
    sender_id: str
    sender_name: str | None = None
    is_self: bool = False
    created_at_ms: int
    content: str = ""


class BehavioralStatsOptions(BaseModel):
    """Configuration options for deterministic behavioral measurement."""

    offset_minutes: int = Field(
        default=480,
        description="Explicit timezone offset in minutes (e.g. +480 for UTC+8). Never rely on host env.",
    )
    min_self_messages: int = Field(
        default=DEFAULT_MIN_SELF_MESSAGES,
        description="Minimum self messages required to produce active hour/weekday histograms.",
    )
    min_latency_samples: int = Field(
        default=DEFAULT_MIN_LATENCY_SAMPLES,
        description="Minimum valid conversational reply samples to produce latency percentiles.",
    )
    max_idle_gap_ms: int = Field(
        default=DEFAULT_MAX_IDLE_GAP_MS,
        description="Maximum idle time between messages to be considered a continuous conversational turn.",
    )
    max_evidence: int = Field(
        default=DEFAULT_MAX_EVIDENCE,
        description="Maximum number of evidence references anchored to each generated candidate.",
    )


class RoutineMeasurement(BaseModel):
    """Strong-typed routine measurement metrics computed purely deterministically."""

    hour_histogram: list[int] = Field(
        default_factory=lambda: [0] * 24,
        description="Message count for each local hour (0-23).",
    )
    weekday_histogram: list[int] = Field(
        default_factory=lambda: [0] * 7,
        description="Message count for each local day of week (0=Mon, 1=Tue, ..., 6=Sun).",
    )
    reply_latency_p50_ms: float | None = Field(
        default=None,
        description="Median response latency (milliseconds) when replying to others. None if insufficient data.",
    )
    reply_latency_p90_ms: float | None = Field(
        default=None,
        description="90th percentile response latency (milliseconds). None if insufficient data.",
    )
    self_message_count: int = Field(
        default=0,
        description="Total count of verified self messages evaluated.",
    )
    latency_sample_count: int = Field(
        default=0,
        description="Total count of valid consecutive reply latency measurements evaluated.",
    )
    channel_distribution: dict[str, int] = Field(
        default_factory=dict,
        description="Distribution of self messages across interaction channels.",
    )
    peak_active_window: str | None = Field(
        default=None,
        description="Estimated continuous peak activity window (e.g. '14:00 - 18:00') if significant.",
    )


def percentile(sorted_values: Sequence[float], p: float) -> float | None:
    """Compute percentile using nearest-rank interpolation to preserve observed reality."""
    if not sorted_values:
        return None
    clamped_p = max(0.0, min(1.0, p))
    index = min(len(sorted_values) - 1, max(0, round((len(sorted_values) - 1) * clamped_p)))
    return sorted_values[index]


def _local_hour_and_weekday(ms: int, offset_minutes: int) -> tuple[int, int]:
    """Compute local hour (0-23) and weekday (0=Mon, 6=Sun) with explicit timezone offset."""
    # Absolute epoch translation to explicit shifted UTC representation
    shifted_dt = datetime.fromtimestamp(ms / 1000.0, tz=UTC) + timedelta(minutes=offset_minutes)
    return shifted_dt.hour, shifted_dt.weekday()


def _resolve_peak_window(hour_histogram: list[int], min_count: int = 10) -> str | None:
    """Identify a 4-hour peak activity window from 24-hour histogram if threshold met."""
    if len(hour_histogram) != 24 or sum(hour_histogram) < min_count:
        return None

    # Sliding 4-hour window with wrap-around
    best_sum = -1
    best_start = 0
    for start in range(24):
        window_sum = sum(hour_histogram[(start + i) % 24] for i in range(4))
        if window_sum > best_sum:
            best_sum = window_sum
            best_start = start

    # Only declare peak if the 4-hour window holds at least 30% of total activity
    total = sum(hour_histogram)
    if total > 0 and (best_sum / total) >= 0.30:
        end = (best_start + 4) % 24
        return f"{best_start:02d}:00 - {end:02d}:00"
    return None


def compute_routine_measurement(
    messages: Sequence[BehavioralMessage],
    options: BehavioralStatsOptions,
) -> RoutineMeasurement:
    """Compute purely deterministic behavioral measurements from conversation logs.

    Enforces strict conversation grouping (per chat_id) and strict sequence pairing:
    Only a verified self-message immediately succeeding another speaker's message
    within max_idle_gap_ms is counted as a response latency sample.
    """
    hour_histogram = [0] * 24
    weekday_histogram = [0] * 7
    channel_counts: dict[str, int] = defaultdict(int)
    latencies: list[float] = []
    self_message_count = 0

    # Group messages by chat_id to maintain conversational coherence
    by_chat: dict[str, list[BehavioralMessage]] = defaultdict(list)
    for msg in messages:
        by_chat[msg.chat_id].append(msg)

    for chat_id, chat_messages in by_chat.items():
        # Strictly chronological within conversation
        sorted_chat = sorted(chat_messages, key=lambda m: m.created_at_ms)
        for idx, msg in enumerate(sorted_chat):
            if not msg.is_self:
                continue

            self_message_count += 1
            channel_counts[msg.channel] += 1

            hour, weekday = _local_hour_and_weekday(msg.created_at_ms, options.offset_minutes)
            hour_histogram[hour] += 1
            weekday_histogram[weekday] += 1

            # Latency definition: self message immediately following a non-self message
            if idx > 0:
                prev = sorted_chat[idx - 1]
                if not prev.is_self:
                    delta_ms = float(msg.created_at_ms - prev.created_at_ms)
                    if 0.0 <= delta_ms <= float(options.max_idle_gap_ms):
                        latencies.append(delta_ms)

    latencies.sort()
    peak_window = _resolve_peak_window(hour_histogram, min_count=options.min_self_messages)

    return RoutineMeasurement(
        hour_histogram=hour_histogram,
        weekday_histogram=weekday_histogram,
        reply_latency_p50_ms=percentile(latencies, 0.5),
        reply_latency_p90_ms=percentile(latencies, 0.9),
        self_message_count=self_message_count,
        latency_sample_count=len(latencies),
        channel_distribution=dict(channel_counts),
        peak_active_window=peak_window,
    )


def generate_behavioral_profile_candidates(
    messages: Sequence[BehavioralMessage],
    options: BehavioralStatsOptions,
) -> list[ExtractedMemory]:
    """Generate structured Profile ExtractedMemory candidates from behavioral measurements.

    Enforces sample-size floor constraints:
    - active_hours & active_weekdays require >= min_self_messages
    - reply_latency_ms requires >= min_latency_samples
    If requirements are not met, candidates are dropped rather than producing noisy estimates.
    """
    measurement = compute_routine_measurement(messages, options)
    self_msgs = [m for m in messages if m.is_self][: options.max_evidence]
    if not self_msgs:
        return []

    evidence_refs = [
        EvidenceReference(
            source_id=f"channel:{m.channel}:{m.chat_id}",
            message_id=m.id,
            channel_id=m.channel,
            timestamp=datetime.fromtimestamp(m.created_at_ms / 1000.0, tz=UTC),
            quote_snippet=m.content[:120] if m.content else None,
            author_id=m.sender_id,
        )
        for m in self_msgs
    ]

    candidates: list[ExtractedMemory] = []

    # Active hours & weekdays histogram candidate
    if measurement.self_message_count >= options.min_self_messages:
        # Confidence smoothly increases with sample volume, capped at 0.90
        hist_conf = min(0.90, 0.50 + measurement.self_message_count / 1000.0)
        hist_value_dict = {
            "hour_histogram": measurement.hour_histogram,
            "weekday_histogram": measurement.weekday_histogram,
            "peak_active_window": measurement.peak_active_window,
            "offset_minutes": options.offset_minutes,
            "sample_count": measurement.self_message_count,
            "channel_distribution": measurement.channel_distribution,
        }
        candidates.append(
            ExtractedMemory(
                memory_type=MemoryType.PROFILE,
                content=(
                    f"User routine active distribution: peak window {measurement.peak_active_window or 'variable'}, "
                    f"offset {options.offset_minutes}m across {measurement.self_message_count} samples"
                ),
                confidence=round(hist_conf, 3),
                importance=0.65,
                profile_key="routine_active_hours",
                profile_value=json.dumps(hist_value_dict, ensure_ascii=False),
                evidence=evidence_refs,
            )
        )

    # Conversational reply latency candidate
    if (
        measurement.latency_sample_count >= options.min_latency_samples
        and measurement.reply_latency_p50_ms is not None
        and measurement.reply_latency_p90_ms is not None
    ):
        lat_conf = min(0.90, 0.50 + measurement.latency_sample_count / 500.0)
        lat_value_dict = {
            "p50_ms": round(measurement.reply_latency_p50_ms, 1),
            "p90_ms": round(measurement.reply_latency_p90_ms, 1),
            "sample_count": measurement.latency_sample_count,
        }
        candidates.append(
            ExtractedMemory(
                memory_type=MemoryType.PROFILE,
                content=(
                    f"User reply latency: P50 {measurement.reply_latency_p50_ms / 1000.0:.1f}s, "
                    f"P90 {measurement.reply_latency_p90_ms / 1000.0:.1f}s across {measurement.latency_sample_count} turns"
                ),
                confidence=round(lat_conf, 3),
                importance=0.60,
                profile_key="routine_reply_latency",
                profile_value=json.dumps(lat_value_dict, ensure_ascii=False),
                evidence=evidence_refs,
            )
        )

    return candidates
