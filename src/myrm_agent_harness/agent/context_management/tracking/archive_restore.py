"""Archived context restore budget DTOs and guidance builders.

[INPUT]
- dataclasses::dataclass, field (POS: Python 数据类装饰器)
- runtime.context.restore_map_contract::* (POS: shared restore-map schema reader and structural restore hints)
- typing::Literal (POS: Python 类型提示)

[OUTPUT]
- ArchiveRestoreBudgetPolicy: per-task archive restore budget policy.
- ArchiveRestoreGuidance: machine-readable restore guidance fields with range and structure hints.
- ArchiveRefetchDecision: archive read allow/block decision.
- build_archive_restore_guidance: restore-map-aware range guidance builder.

[POS]
Archive restore DTO layer. Defines stable budget, decision, and restore-map-aware flat guidance contracts for archived context reads.
"""

from dataclasses import dataclass, field
from typing import Literal

from myrm_agent_harness.runtime.context.restore_map_contract import (
    RestoreContentFeature,
    RestoreRangeHint,
    load_restore_map_ranges,
)

MAX_ARCHIVE_REFETCHES_PER_PATH = 2
MAX_ARCHIVE_REFETCH_TOKENS = 16_000
MAX_ARCHIVE_FULL_RESTORE_TOKENS = 2_000
ARCHIVE_RESTORE_RANGE_CHUNK_LINES = 200
ARCHIVE_RESTORE_BACKOFF_RANGE_CHUNK_LINES = 100
ARCHIVE_RESTORE_GUIDANCE_RANGE_COUNT = 3

RestoreSeverity = Literal["info", "warning", "critical"]
RestoreGuidanceSource = Literal["restore_map", "fallback"]


@dataclass(frozen=True, slots=True)
class ArchiveRestoreBudgetPolicy:
    """Per-task budget policy for restoring archived context."""

    max_refetches_per_path: int = MAX_ARCHIVE_REFETCHES_PER_PATH
    max_refetch_tokens: int = MAX_ARCHIVE_REFETCH_TOKENS
    max_full_restore_tokens: int = MAX_ARCHIVE_FULL_RESTORE_TOKENS


DEFAULT_ARCHIVE_RESTORE_BUDGET_POLICY = ArchiveRestoreBudgetPolicy()


@dataclass(frozen=True, slots=True)
class ArchiveRestoreGuidance:
    """Machine-readable guidance for restoring archived context."""

    reason_label_key: str = ""
    severity: RestoreSeverity = "warning"
    primary_restore_arg: str = ""
    recommended_ranges: tuple[str, ...] = ()
    restore_range_hints: tuple[RestoreRangeHint, ...] = ()
    content_features: tuple[RestoreContentFeature, ...] = ()
    guidance_source: RestoreGuidanceSource = "fallback"
    fallback_reason: str = ""
    backoff_adjusted: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "reason_label_key": self.reason_label_key,
            "severity": self.severity,
            "primary_restore_arg": self.primary_restore_arg,
            "recommended_ranges": list(self.recommended_ranges),
            "restore_range_hints": [hint.to_dict() for hint in self.restore_range_hints],
            "content_features": [feature.to_dict() for feature in self.content_features],
            "guidance_source": self.guidance_source,
            "fallback_reason": self.fallback_reason,
            "backoff_adjusted": self.backoff_adjusted,
        }


@dataclass(frozen=True, slots=True)
class ArchiveRefetchDecision:
    """Decision for an attempted archived context read."""

    is_archive_path: bool
    allowed: bool
    recorded: bool
    reason: str = ""
    message: str = ""
    suggested_action: str = ""
    guidance: ArchiveRestoreGuidance = field(default_factory=ArchiveRestoreGuidance)

    def to_blocked_payload(self, archive_path: str, estimated_tokens: int) -> dict[str, object]:
        """Return a stable machine-readable payload for blocked archive reads."""
        guidance_payload = self.guidance.to_dict()
        return {
            "type": "archive_restore_blocked",
            "reason": self.reason,
            "message": self.message,
            "suggested_action": self.suggested_action,
            "archive_path": archive_path,
            "estimated_tokens": max(estimated_tokens, 0),
            **guidance_payload,
        }


def build_archive_restore_guidance(
    archive_path: str,
    *,
    reason: str,
    severity: RestoreSeverity = "warning",
    chunk_size_lines: int = ARCHIVE_RESTORE_RANGE_CHUNK_LINES,
    max_ranges: int = ARCHIVE_RESTORE_GUIDANCE_RANGE_COUNT,
    backoff_adjusted: bool = False,
) -> ArchiveRestoreGuidance:
    """Build stable line-range restore args, preferring a restore-map sidecar when present."""
    if not archive_path:
        return ArchiveRestoreGuidance(reason_label_key=reason, severity=severity, backoff_adjusted=backoff_adjusted)

    safe_chunk_size = max(chunk_size_lines, 1)
    safe_range_count = max(max_ranges, 1)
    if backoff_adjusted:
        safe_chunk_size = min(safe_chunk_size, ARCHIVE_RESTORE_BACKOFF_RANGE_CHUNK_LINES)
        safe_range_count = 1
    restore_map = load_restore_map_ranges(archive_path, safe_range_count)
    ranges = restore_map.ranges
    if not ranges:
        ranges = tuple(
            f"{archive_path}:{start}-{start + safe_chunk_size - 1}"
            for start in range(1, safe_chunk_size * safe_range_count + 1, safe_chunk_size)
        )
    range_hints = restore_map.range_hints or _fallback_range_hints(ranges)
    return ArchiveRestoreGuidance(
        reason_label_key=reason,
        severity=severity,
        primary_restore_arg=ranges[0],
        recommended_ranges=ranges,
        restore_range_hints=range_hints,
        content_features=restore_map.content_features,
        guidance_source="restore_map" if restore_map.found else "fallback",
        fallback_reason=restore_map.fallback_reason,
        backoff_adjusted=backoff_adjusted,
    )


def _fallback_range_hints(ranges: tuple[str, ...]) -> tuple[RestoreRangeHint, ...]:
    hints: list[RestoreRangeHint] = []
    for restore_range in ranges:
        _, _, line_span = restore_range.rpartition(":")
        raw_start, _, raw_end = line_span.partition("-")
        try:
            start_line = int(raw_start)
            end_line = int(raw_end)
        except ValueError:
            continue
        hints.append(
            RestoreRangeHint(
                range_arg=restore_range,
                reason="fallback_chunk",
                start_line=start_line,
                end_line=end_line,
                line=start_line,
            )
        )
    return tuple(hints)


__all__ = [
    "ARCHIVE_RESTORE_BACKOFF_RANGE_CHUNK_LINES",
    "ARCHIVE_RESTORE_GUIDANCE_RANGE_COUNT",
    "ARCHIVE_RESTORE_RANGE_CHUNK_LINES",
    "DEFAULT_ARCHIVE_RESTORE_BUDGET_POLICY",
    "MAX_ARCHIVE_FULL_RESTORE_TOKENS",
    "MAX_ARCHIVE_REFETCHES_PER_PATH",
    "MAX_ARCHIVE_REFETCH_TOKENS",
    "ArchiveRefetchDecision",
    "ArchiveRestoreBudgetPolicy",
    "ArchiveRestoreGuidance",
    "RestoreGuidanceSource",
    "RestoreSeverity",
    "build_archive_restore_guidance",
]
