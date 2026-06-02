"""Task metric event DTOs.

[INPUT]
- dataclasses::dataclass, field (POS: Python 数据类装饰器)
- datetime::datetime (POS: Python 日期时间)
- typing::Literal (POS: Python 类型提示)
- tracking.archive_restore::ArchiveRestoreGuidance (POS: 归档恢复扁平指引 DTO)

[OUTPUT]
- CompressionEvent: compression metric event.
- RefetchEvent: restored-information refetch event.
- ArchiveRestoreOutcomeEvent: allowed/blocked archive restore decision event.
- ArchiveRestoreResultEvent: successful archive restore materialization event.
- ArchiveRestoreBlockEvent: blocked archive restore event.
- sanitize_count_map: positive integer count-map normalizer.

[POS]
Task metric event DTO layer. Defines serializable compression, adaptive pruning backoff, refetch,
restore outcome, restore result, and restore-block event records.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from .archive_restore import ArchiveRestoreGuidance


@dataclass
class CompressionEvent:
    """压缩事件记录"""

    timestamp: datetime
    tokens_saved: int
    compression_type: Literal["filter", "cache_ttl_prune", "compress", "summarize"]
    details: str = ""
    group_count: int = 0
    dedup_tokens_saved: int = 0
    integrity_skipped: int = 0
    archive_count: int = 0
    soft_trimmed_count: int = 0
    offload_failed_count: int = 0
    offload_failure_kinds: dict[str, int] = field(default_factory=dict)
    deferred_count: int = 0
    deferred_reasons: dict[str, int] = field(default_factory=dict)
    archive_deferred_count: int = 0
    archive_deferred_reasons: dict[str, int] = field(default_factory=dict)
    archive_deferred_soft_trimmed_count: int = 0
    archive_deferred_soft_trimmed_reasons: dict[str, int] = field(default_factory=dict)
    original_tokens: int = 0
    archive_written_count: int = 0
    archive_reused_count: int = 0
    archive_bytes_written: int = 0
    archive_bytes_reused: int = 0
    backoff_applied: bool = False
    backoff_reasons: list[str] = field(default_factory=list)
    effective_soft_trim_ratio: float = 0.0
    effective_hard_clear_ratio: float = 0.0
    effective_min_prunable_tokens: int = 0
    backoff_sample_count: int = 0
    backoff_bad_signal_count: int = 0
    backoff_recovery_sample_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "tokens_saved": self.tokens_saved,
            "compression_type": self.compression_type,
            "details": self.details,
            "group_count": self.group_count,
            "dedup_tokens_saved": self.dedup_tokens_saved,
            "integrity_skipped": self.integrity_skipped,
            "archive_count": self.archive_count,
            "soft_trimmed_count": self.soft_trimmed_count,
            "offload_failed_count": self.offload_failed_count,
            "offload_failure_kinds": dict(self.offload_failure_kinds),
            "deferred_count": self.deferred_count,
            "deferred_reasons": dict(self.deferred_reasons),
            "archive_deferred_count": self.archive_deferred_count,
            "archive_deferred_reasons": dict(self.archive_deferred_reasons),
            "archive_deferred_soft_trimmed_count": self.archive_deferred_soft_trimmed_count,
            "archive_deferred_soft_trimmed_reasons": dict(self.archive_deferred_soft_trimmed_reasons),
            "original_tokens": self.original_tokens,
            "archive_written_count": self.archive_written_count,
            "archive_reused_count": self.archive_reused_count,
            "archive_bytes_written": self.archive_bytes_written,
            "archive_bytes_reused": self.archive_bytes_reused,
            "backoff_applied": self.backoff_applied,
            "backoff_reasons": list(self.backoff_reasons),
            "effective_soft_trim_ratio": self.effective_soft_trim_ratio,
            "effective_hard_clear_ratio": self.effective_hard_clear_ratio,
            "effective_min_prunable_tokens": self.effective_min_prunable_tokens,
            "backoff_sample_count": self.backoff_sample_count,
            "backoff_bad_signal_count": self.backoff_bad_signal_count,
            "backoff_recovery_sample_count": self.backoff_recovery_sample_count,
        }


@dataclass
class RefetchEvent:
    """重新获取事件记录(因压缩丢失信息导致)"""

    timestamp: datetime
    reason: str
    tool_name: str = ""
    estimated_tokens: int = 0
    archive_path: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "reason": self.reason,
            "tool_name": self.tool_name,
            "estimated_tokens": self.estimated_tokens,
            "archive_path": self.archive_path,
        }


@dataclass
class ArchiveRestoreOutcomeEvent:
    """Archived context restore allow/block outcome event."""

    timestamp: datetime
    outcome: Literal["allowed", "blocked"]
    reason: str = ""
    estimated_tokens: int = 0
    archive_path: str = ""
    recorded: bool = False
    is_range_read: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "outcome": self.outcome,
            "reason": self.reason,
            "estimated_tokens": self.estimated_tokens,
            "archive_path": self.archive_path,
            "recorded": self.recorded,
            "is_range_read": self.is_range_read,
        }


@dataclass
class ArchiveRestoreResultEvent:
    """Successful archived context restore result event without restored content."""

    timestamp: datetime
    archive_path: str
    restore_arg: str
    start_line: int
    end_line: int
    restored_line_count: int
    estimated_tokens: int = 0
    restored_bytes: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "archive_path": self.archive_path,
            "restore_arg": self.restore_arg,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "restored_line_count": self.restored_line_count,
            "estimated_tokens": self.estimated_tokens,
            "restored_bytes": self.restored_bytes,
            "outcome": "restored",
        }


@dataclass
class ArchiveRestoreBlockEvent:
    """Archived context restore block event."""

    timestamp: datetime
    reason: str
    estimated_tokens: int = 0
    archive_path: str = ""
    message: str = ""
    suggested_action: str = ""
    guidance: ArchiveRestoreGuidance = field(default_factory=ArchiveRestoreGuidance)

    def to_dict(self) -> dict[str, object]:
        guidance_payload = self.guidance.to_dict()
        return {
            "timestamp": self.timestamp.isoformat(),
            "reason": self.reason,
            "estimated_tokens": self.estimated_tokens,
            "archive_path": self.archive_path,
            "message": self.message,
            "suggested_action": self.suggested_action,
            **guidance_payload,
        }


def sanitize_count_map(value: dict[str, int] | None) -> dict[str, int]:
    if value is None:
        return {}
    return {str(kind): count for kind, count in value.items() if isinstance(count, int) and count > 0}


def sanitize_string_list(value: list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []
    return [item for item in value if item]


__all__ = [
    "ArchiveRestoreBlockEvent",
    "ArchiveRestoreOutcomeEvent",
    "ArchiveRestoreResultEvent",
    "CompressionEvent",
    "RefetchEvent",
    "sanitize_count_map",
    "sanitize_string_list",
]
