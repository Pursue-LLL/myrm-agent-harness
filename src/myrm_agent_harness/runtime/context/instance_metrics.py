"""Context operation metrics for monitoring and observability.

Instance-level metrics for context offload, compression, cleanup operations.
Business layer can aggregate across instances and push to monitoring systems.

Design Principles:
- Instance-level: Each agent instance maintains its own metrics
- No global state: No Prometheus/OpenTelemetry dependencies
- Export interface: .to_dict() for business layer integration
- Similar to CheckpointMetrics and resource_report.json design

Usage with contextvars (async-safe):
    ```python
    from myrm_agent_harness.runtime.context.instance_metrics import (
        ContextMetrics,
        set_context_metrics,
    )

    # At agent initialization
    metrics = ContextMetrics()
    set_context_metrics(metrics)

    # In any async function
    # Metrics are automatically recorded if context_metrics is set
    ```

[INPUT]
- (none)

[OUTPUT]
- OffloadMetrics: Offload operation metrics.
- CompressionMetrics: Compression operation metrics.
- DecompressionMetrics: Decompression operation metrics.
- CleanupMetrics: Cleanup operation metrics.
- FileAccessMetrics: File access metrics.

[POS]
Context operation metrics for monitoring and observability.
"""

from __future__ import annotations

import contextvars
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TypedDict, TypeVar

# Type variable for generic list trimming
T = TypeVar("T", int, float)

# Context variable for async-safe metrics propagation
context_metrics_var: contextvars.ContextVar[ContextMetrics | None] = contextvars.ContextVar(
    "context_metrics", default=None
)


# TypedDict definitions for .to_dict() return type
class OffloadMetrics(TypedDict):
    """Offload operation metrics."""

    total_operations: int
    success_count: int
    failure_count: int
    total_bytes: int
    avg_duration_ms: float
    avg_bytes: float
    by_tool: dict[tuple[str, str], int]


class CompressionMetrics(TypedDict):
    """Compression operation metrics."""

    count: int
    avg_duration_ms: float
    avg_ratio: float
    bytes_saved: int


class DecompressionMetrics(TypedDict):
    """Decompression operation metrics."""

    total_operations: int
    success_rate: float
    avg_duration_ms: float
    by_status: dict[str, int]


class CleanupMetrics(TypedDict):
    """Cleanup operation metrics."""

    total_operations: int
    avg_files_removed: float
    avg_duration_ms: float
    by_type: dict[str, int]
    phase_durations_ms: dict[str, float]
    protection_hits: dict[str, int]


class FileAccessMetrics(TypedDict):
    """File access metrics."""

    count: int
    avg_tracker_records: float


class QuotaMetrics(TypedDict):
    """Quota operation metrics."""

    check_count: dict[str, int]
    avg_usage_bytes: float
    exceeded_count: int


class BatchQueryTypeMetrics(TypedDict):
    """Per-query-type batch query metrics."""

    count: int
    avg_size: float
    avg_duration_ms: float


class BatchQueryMetrics(TypedDict):
    """Batch query metrics."""

    by_type: dict[str, BatchQueryTypeMetrics]


class MetricsExport(TypedDict):
    """Complete metrics export structure.

    Structured format for business layer integration.
    All durations are in milliseconds, all sizes in bytes.
    """

    offload: OffloadMetrics
    compression: CompressionMetrics
    decompression: DecompressionMetrics
    cleanup: CleanupMetrics
    file_access: FileAccessMetrics
    quota: QuotaMetrics
    batch_query: BatchQueryMetrics


# Memory safety: Limit list sizes to prevent unbounded growth in long-running agents
# Business layer should read and export metrics periodically
MAX_LIST_SIZE = 1000  # Keep last 1000 samples
TRIM_TO_SIZE = 500  # Trim to this size when limit reached


@dataclass
class ContextMetrics:
    """Context operation metrics for a single agent instance.

    Tracks performance and behavior of context management operations:
    - Offload: Success/failure counts, bytes, duration
    - Compression: Ratio, duration, bytes saved
    - Cleanup: Operations, files removed, phase timings
    - File access: Tracking operations
    - Quota: Check results, usage, exceeded events

    All durations are in milliseconds for precision.
    Business layer can convert to seconds for Prometheus if needed.
    """

    # Offload operations by (tool_name, status)
    offload_count: dict[tuple[str, str], int] = field(default_factory=lambda: defaultdict(int))
    offload_total_bytes: int = 0
    offload_total_duration_ms: float = 0.0
    offload_operation_count: int = 0  # Total operations for averaging

    # Compression operations
    compression_count: int = 0
    compression_total_duration_ms: float = 0.0
    compression_bytes_saved: int = 0
    compression_ratios: list[float] = field(default_factory=list)  # For distribution analysis

    # Decompression operations by status
    decompression_count: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    decompression_total_duration_ms: float = 0.0
    decompression_operation_count: int = 0

    # Cleanup operations by type
    cleanup_count: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    cleanup_files_removed: list[int] = field(default_factory=list)
    cleanup_total_duration_ms: float = 0.0
    cleanup_active_sessions: list[int] = field(default_factory=list)

    # Cleanup phase timings by phase name
    cleanup_phase_durations_ms: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    # Protection rule hits by rule name
    protection_rule_hits: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    # File access tracking
    file_access_count: int = 0
    file_access_tracker_records: list[int] = field(default_factory=list)

    # Quota operations
    quota_check_count: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    quota_usage_bytes: list[int] = field(default_factory=list)
    quota_exceeded_count: int = 0

    # Batch query performance by query type
    batch_query_count: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    batch_query_sizes: dict[str, list[int]] = field(default_factory=lambda: defaultdict(list))
    batch_query_durations_ms: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))

    # Computed properties
    @property
    def offload_avg_duration_ms(self) -> float:
        """Average offload duration in milliseconds."""
        return (
            self.offload_total_duration_ms / self.offload_operation_count if self.offload_operation_count > 0 else 0.0
        )

    @property
    def offload_avg_bytes(self) -> float:
        """Average bytes per offload operation."""
        return self.offload_total_bytes / self.offload_operation_count if self.offload_operation_count > 0 else 0.0

    @property
    def compression_avg_ratio(self) -> float:
        """Average compression ratio."""
        return sum(self.compression_ratios) / len(self.compression_ratios) if self.compression_ratios else 0.0

    @property
    def decompression_success_rate(self) -> float:
        """Decompression success rate (0.0 to 1.0)."""
        success = self.decompression_count.get("success", 0)
        total = sum(self.decompression_count.values())
        return success / total if total > 0 else 1.0

    @property
    def cleanup_avg_files_removed(self) -> float:
        """Average files removed per cleanup operation."""
        return sum(self.cleanup_files_removed) / len(self.cleanup_files_removed) if self.cleanup_files_removed else 0.0

    def _trim_list_if_needed(self, data_list: list[T]) -> None:
        """Trim list to prevent unbounded memory growth.

        Keeps most recent TRIM_TO_SIZE samples when MAX_LIST_SIZE is reached.
        Business layer should periodically export metrics to avoid data loss.

        Args:
            data_list: List to trim (modified in-place)

        Note:
            Called BEFORE append to ensure list size never exceeds MAX_LIST_SIZE.
        """
        if len(data_list) >= MAX_LIST_SIZE:
            # Keep most recent samples (FIFO), remove enough space for new item
            del data_list[: len(data_list) - TRIM_TO_SIZE + 1]

    def to_dict(self) -> MetricsExport:
        """Export metrics for business layer monitoring.

        Returns:
            Structured dictionary with complete type information.
            See `MetricsExport` TypedDict for detailed structure.

            Business layer can push to Prometheus/DataDog/logs as needed.

        Note:
            All durations are in milliseconds, all sizes in bytes.
            TypedDict provides static type checking and IDE autocomplete.
        """
        return {
            # Offload metrics
            "offload": {
                "total_operations": self.offload_operation_count,
                "success_count": self.offload_count.get(("*", "success"), 0),
                "failure_count": self.offload_count.get(("*", "failure"), 0),
                "total_bytes": self.offload_total_bytes,
                "avg_duration_ms": self.offload_avg_duration_ms,
                "avg_bytes": self.offload_avg_bytes,
                "by_tool": dict(self.offload_count),  # Convert defaultdict to dict
            },
            # Compression metrics
            "compression": {
                "count": self.compression_count,
                "avg_duration_ms": (
                    self.compression_total_duration_ms / self.compression_count if self.compression_count > 0 else 0.0
                ),
                "avg_ratio": self.compression_avg_ratio,
                "bytes_saved": self.compression_bytes_saved,
            },
            # Decompression metrics
            "decompression": {
                "total_operations": self.decompression_operation_count,
                "success_rate": self.decompression_success_rate,
                "avg_duration_ms": (
                    self.decompression_total_duration_ms / self.decompression_operation_count
                    if self.decompression_operation_count > 0
                    else 0.0
                ),
                "by_status": dict(self.decompression_count),
            },
            # Cleanup metrics
            "cleanup": {
                "total_operations": sum(self.cleanup_count.values()),
                "avg_files_removed": self.cleanup_avg_files_removed,
                "avg_duration_ms": (
                    self.cleanup_total_duration_ms / sum(self.cleanup_count.values())
                    if sum(self.cleanup_count.values()) > 0
                    else 0.0
                ),
                "by_type": dict(self.cleanup_count),
                "phase_durations_ms": {
                    phase: (sum(durations) / len(durations) if durations else 0.0)
                    for phase, durations in self.cleanup_phase_durations_ms.items()
                },
                "protection_hits": dict(self.protection_rule_hits),
            },
            # File access metrics
            "file_access": {
                "count": self.file_access_count,
                "avg_tracker_records": (
                    sum(self.file_access_tracker_records) / len(self.file_access_tracker_records)
                    if self.file_access_tracker_records
                    else 0.0
                ),
            },
            # Quota metrics
            "quota": {
                "check_count": dict(self.quota_check_count),
                "avg_usage_bytes": (
                    sum(self.quota_usage_bytes) / len(self.quota_usage_bytes) if self.quota_usage_bytes else 0.0
                ),
                "exceeded_count": self.quota_exceeded_count,
            },
            # Batch query metrics
            "batch_query": {
                "by_type": {
                    query_type: {
                        "count": self.batch_query_count[query_type],
                        "avg_size": (
                            sum(self.batch_query_sizes[query_type]) / len(self.batch_query_sizes[query_type])
                            if self.batch_query_sizes[query_type]
                            else 0.0
                        ),
                        "avg_duration_ms": (
                            sum(self.batch_query_durations_ms[query_type])
                            / len(self.batch_query_durations_ms[query_type])
                            if self.batch_query_durations_ms[query_type]
                            else 0.0
                        ),
                    }
                    for query_type in self.batch_query_count
                },
            },
        }

    # Instance methods for recording metrics
    def record_offload_success(self, tool_name: str, content_bytes: int, duration_ms: float) -> None:
        """Record successful context offload operation.

        Args:
            tool_name: Name of the tool
            content_bytes: Size of content in bytes
            duration_ms: Duration in milliseconds
        """
        self.offload_count[(tool_name, "success")] += 1
        self.offload_count[("*", "success")] += 1  # Aggregate across all tools
        self.offload_total_bytes += content_bytes
        self.offload_total_duration_ms += duration_ms
        self.offload_operation_count += 1

    def record_offload_failure(self, tool_name: str) -> None:
        """Record failed context offload operation.

        Args:
            tool_name: Name of the tool
        """
        self.offload_count[(tool_name, "failure")] += 1
        self.offload_count[("*", "failure")] += 1
        self.offload_operation_count += 1

    def record_cleanup(self, cleanup_type: str, files_removed: int) -> None:
        """Record context cleanup operation.

        Args:
            cleanup_type: Type of cleanup ('session', 'orphan')
            files_removed: Number of files removed
        """
        self.cleanup_count[cleanup_type] += 1
        self._trim_list_if_needed(self.cleanup_files_removed)
        self.cleanup_files_removed.append(files_removed)

    def record_compression(
        self,
        original_bytes: int,
        compressed_bytes: int,
        duration_ms: float,
    ) -> None:
        """Record compression operation metrics.

        Args:
            original_bytes: Original content size in bytes
            compressed_bytes: Compressed content size in bytes
            duration_ms: Compression duration in milliseconds
        """
        self.compression_count += 1
        self.compression_total_duration_ms += duration_ms

        if compressed_bytes > 0:
            ratio = original_bytes / compressed_bytes
            self._trim_list_if_needed(self.compression_ratios)
            self.compression_ratios.append(ratio)

        bytes_saved = original_bytes - compressed_bytes
        if bytes_saved > 0:
            self.compression_bytes_saved += bytes_saved

    def record_decompression(self, duration_ms: float, success: bool = True) -> None:
        """Record decompression operation metrics.

        Args:
            duration_ms: Decompression duration in milliseconds
            success: Whether decompression succeeded
        """
        status = "success" if success else "failure"
        self.decompression_count[status] += 1
        self.decompression_operation_count += 1

        if success:
            self.decompression_total_duration_ms += duration_ms

    def record_file_access(self) -> None:
        """Record file access event."""
        self.file_access_count += 1

    def record_quota_check(self, allowed: bool) -> None:
        """Record quota check operation.

        Args:
            allowed: Whether write was allowed
        """
        status = "allowed" if allowed else "denied"
        self.quota_check_count[status] += 1

    def record_quota_usage(self, usage_bytes: int) -> None:
        """Record current storage usage for session.

        Args:
            usage_bytes: Current usage in bytes
        """
        self._trim_list_if_needed(self.quota_usage_bytes)
        self.quota_usage_bytes.append(usage_bytes)

    def record_quota_exceeded(self) -> None:
        """Record quota exceeded event."""
        self.quota_exceeded_count += 1

    def record_cleanup_duration(self, cleanup_type: str, duration_ms: float) -> None:
        """Record cleanup operation duration.

        Args:
            cleanup_type: Type of cleanup operation
            duration_ms: Duration in milliseconds
        """
        self.cleanup_total_duration_ms += duration_ms

    def record_cleanup_active_sessions(self, count: int) -> None:
        """Record number of active sessions detected during cleanup.

        Args:
            count: Number of active sessions
        """
        self._trim_list_if_needed(self.cleanup_active_sessions)
        self.cleanup_active_sessions.append(count)

    def record_tracker_statistics(self, access_tracker_records: int = 0) -> None:
        """Record tracker database statistics.

        Args:
            access_tracker_records: Number of records in access tracker
        """
        if access_tracker_records > 0:
            self._trim_list_if_needed(self.file_access_tracker_records)
            self.file_access_tracker_records.append(access_tracker_records)

    def record_cleanup_phase_duration(self, phase: str, duration_ms: float) -> None:
        """Record duration of a specific cleanup phase.

        Args:
            phase: Phase name ('session_loading', 'file_scanning',
                   'deletion', 'orphan_cleanup')
            duration_ms: Duration in milliseconds
        """
        self._trim_list_if_needed(self.cleanup_phase_durations_ms[phase])
        self.cleanup_phase_durations_ms[phase].append(duration_ms)

    def record_protection_rule_hit(self, rule: str) -> None:
        """Record file protected by a specific rule.

        Args:
            rule: Rule name ('session_active', 'access_tracked', 'mtime_fallback')
        """
        self.protection_rule_hits[rule] += 1

    def record_batch_query(self, query_type: str, item_count: int, duration_ms: float) -> None:
        """Record batch query performance.

        Args:
            query_type: Type of query ('access_check', 'reference_check')
            item_count: Number of items in the batch
            duration_ms: Query duration in milliseconds
        """
        self.batch_query_count[query_type] += 1
        self._trim_list_if_needed(self.batch_query_sizes[query_type])
        self.batch_query_sizes[query_type].append(item_count)
        self._trim_list_if_needed(self.batch_query_durations_ms[query_type])
        self.batch_query_durations_ms[query_type].append(duration_ms)


# Helper functions for contextvars-based metrics propagation
def set_context_metrics(metrics: ContextMetrics | None) -> contextvars.Token[ContextMetrics | None]:
    """Set context metrics for current async context.

    Args:
        metrics: ContextMetrics instance or None to disable

    Returns:
        Token for resetting later if needed

    Example:
        >>> metrics = ContextMetrics()
        >>> token = set_context_metrics(metrics)
        >>> # All operations in this context will record to metrics
        >>> # context_metrics_var.reset(token)  # Reset if needed
    """
    return context_metrics_var.set(metrics)


def get_context_metrics() -> ContextMetrics | None:
    """Get context metrics from current async context.

    Returns:
        ContextMetrics instance if set, None otherwise
    """
    return context_metrics_var.get()


# Module-level compatibility functions (safe to call without metrics set)
def record_offload_success(tool_name: str, content_bytes: int, duration_seconds: float) -> None:
    """Record successful context offload operation.

    Compatibility function that works with contextvars.
    Silently skips if context_metrics is not set.

    Args:
        tool_name: Name of the tool
        content_bytes: Size of content in bytes
        duration_seconds: Duration in seconds
    """
    metrics = get_context_metrics()
    if metrics:
        metrics.record_offload_success(tool_name, content_bytes, duration_seconds * 1000)


def record_offload_failure(tool_name: str) -> None:
    """Record failed context offload operation.

    Args:
        tool_name: Name of the tool
    """
    metrics = get_context_metrics()
    if metrics:
        metrics.record_offload_failure(tool_name)


def record_cleanup(cleanup_type: str, files_removed: int) -> None:
    """Record context cleanup operation.

    Args:
        cleanup_type: Type of cleanup ('session', 'orphan')
        files_removed: Number of files removed
    """
    metrics = get_context_metrics()
    if metrics:
        metrics.record_cleanup(cleanup_type, files_removed)


def record_compression(
    original_bytes: int,
    compressed_bytes: int,
    duration_seconds: float,
) -> None:
    """Record compression operation metrics.

    Args:
        original_bytes: Original content size in bytes
        compressed_bytes: Compressed content size in bytes
        duration_seconds: Compression duration in seconds
    """
    metrics = get_context_metrics()
    if metrics:
        metrics.record_compression(original_bytes, compressed_bytes, duration_seconds * 1000)


def record_decompression(duration_seconds: float, success: bool = True) -> None:
    """Record decompression operation metrics.

    Args:
        duration_seconds: Decompression duration in seconds
        success: Whether decompression succeeded
    """
    metrics = get_context_metrics()
    if metrics:
        metrics.record_decompression(duration_seconds * 1000, success)


def record_file_access() -> None:
    """Record file access event."""
    metrics = get_context_metrics()
    if metrics:
        metrics.record_file_access()


def record_quota_check(allowed: bool) -> None:
    """Record quota check operation.

    Args:
        allowed: Whether write was allowed
    """
    metrics = get_context_metrics()
    if metrics:
        metrics.record_quota_check(allowed)


def record_quota_usage(usage_bytes: int) -> None:
    """Record current storage usage for session.

    Args:
        usage_bytes: Current usage in bytes
    """
    metrics = get_context_metrics()
    if metrics:
        metrics.record_quota_usage(usage_bytes)


def record_quota_exceeded() -> None:
    """Record quota exceeded event."""
    metrics = get_context_metrics()
    if metrics:
        metrics.record_quota_exceeded()


def record_cleanup_duration(cleanup_type: str, duration_seconds: float) -> None:
    """Record cleanup operation duration.

    Args:
        cleanup_type: Type of cleanup operation
        duration_seconds: Duration in seconds
    """
    metrics = get_context_metrics()
    if metrics:
        metrics.record_cleanup_duration(cleanup_type, duration_seconds * 1000)


def record_cleanup_active_sessions(count: int) -> None:
    """Record number of active sessions detected during cleanup.

    Args:
        count: Number of active sessions
    """
    metrics = get_context_metrics()
    if metrics:
        metrics.record_cleanup_active_sessions(count)


def record_tracker_statistics(access_tracker_records: int = 0) -> None:
    """Record tracker database statistics.

    Args:
        access_tracker_records: Number of records in access tracker
    """
    metrics = get_context_metrics()
    if metrics:
        metrics.record_tracker_statistics(access_tracker_records)


def record_cleanup_phase_duration(phase: str, duration_seconds: float) -> None:
    """Record duration of a specific cleanup phase.

    Args:
        phase: Phase name ('session_loading', 'file_scanning',
               'deletion', 'orphan_cleanup')
        duration_seconds: Duration in seconds
    """
    metrics = get_context_metrics()
    if metrics:
        metrics.record_cleanup_phase_duration(phase, duration_seconds * 1000)


def record_protection_rule_hit(rule: str) -> None:
    """Record file protected by a specific rule.

    Args:
        rule: Rule name ('session_active', 'access_tracked', 'mtime_fallback')
    """
    metrics = get_context_metrics()
    if metrics:
        metrics.record_protection_rule_hit(rule)


def record_batch_query(query_type: str, item_count: int, duration_seconds: float) -> None:
    """Record batch query performance.

    Args:
        query_type: Type of query ('access_check', 'reference_check')
        item_count: Number of items in the batch
        duration_seconds: Query duration in seconds
    """
    metrics = get_context_metrics()
    if metrics:
        metrics.record_batch_query(query_type, item_count, duration_seconds * 1000)
