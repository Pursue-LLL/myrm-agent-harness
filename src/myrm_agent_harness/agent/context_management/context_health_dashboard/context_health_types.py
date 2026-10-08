# [INPUT]: None
# [OUTPUT]: ContextHealthConfig, ContextSavingsMetrics, ContextUsageSnapshot, HealthDoctorDiagnosis, HealthWatermarkLevel, PurgeReceipt, ToolExpenditureItem
# [POS]: agent/context_management/context_health_dashboard/context_health_types.py

"""Domain models and contracts for realtime context health dashboard and ephemeral auto-purge sentry.

[INPUT]
- None (Self-contained domain models for context metrics and cleanup).

[OUTPUT]
- HealthWatermarkLevel: Health indicator level (HEALTHY, WARNING, CRITICAL, OVERFLOW).
- ContextUsageSnapshot: Realtime window utilization, safe headroom, and watermark state.
- ToolExpenditureItem: Individual tool consumption metric with share percentage.
- ContextSavingsMetrics: Data compression/sandbox offload savings ratio and multiplier.
- PurgeReceipt: Result summary of cleaning ephemeral session caches and indexes.
- HealthDoctorDiagnosis: System health check outcome and remediation advice.
- ContextHealthConfig: Settings controlling watermarks, thresholds, and top-n limits.

[POS]
Domain contract layer for context health dashboard in context management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Sequence


class HealthWatermarkLevel(str, Enum):
    """Watermark status of context window capacity."""

    HEALTHY = "healthy"          # < 75% usage
    WARNING = "warning"          # 75% - 90% usage
    CRITICAL = "critical"        # 90% - 100% usage
    OVERFLOW = "overflow"        # >= 100% usage


@dataclass(frozen=True)
class ToolExpenditureItem:
    """Tool invocation footprint and payload volume metric."""

    tool_name: str
    call_count: int
    raw_chars: int
    token_estimate: int
    share_percentage: float


@dataclass(frozen=True)
class ContextSavingsMetrics:
    """Mathematical metric evaluating context window tokens saved through offload/compression."""

    raw_unbounded_tokens: int
    context_resident_tokens: int
    tokens_saved: int
    savings_ratio_pct: float     # e.g., 92.4%
    savings_multiplier_x: float  # e.g., 13.2x (raw / resident)


@dataclass(frozen=True)
class ContextUsageSnapshot:
    """Realtime capacity meter measuring resident context size against model window."""

    session_id: str
    current_tokens: int
    window_capacity_tokens: int
    usage_percentage: float
    safe_headroom_tokens: int
    watermark_level: HealthWatermarkLevel
    top_tools: Sequence[ToolExpenditureItem]
    savings: ContextSavingsMetrics


@dataclass(frozen=True)
class PurgeReceipt:
    """Receipt returned after purging ephemeral session caches and SQLite vaults."""

    session_id: str
    purged_files_count: int
    reclaimed_bytes: int
    duration_ms: float
    target_directory: str
    status: str = "success"


@dataclass(frozen=True)
class HealthDoctorDiagnosis:
    """Health check outcome evaluating environment capabilities and storage permissions."""

    fts5_supported: bool
    trigram_supported: bool
    storage_writable: bool
    available_disk_mb: int
    orphaned_files_detected: int
    is_healthy: bool
    remediation_recommendations: Sequence[str] = field(default_factory=tuple)


@dataclass(frozen=True)
class ContextHealthConfig:
    """Configuration governing watermarks, top-N tools, and auto-purge paths."""

    default_window_capacity: int = 128_000
    warning_watermark_ratio: float = 0.75
    critical_watermark_ratio: float = 0.90
    top_tools_limit: int = 5
    base_ephemeral_dir_template: str = ".context/{session_id}"
