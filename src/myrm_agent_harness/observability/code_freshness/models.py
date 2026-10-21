"""
[INPUT]: Process start timestamps, module source filepaths, and disk modification metadata.
[OUTPUT]: Pydantic schemas representing three-state code freshness determinations, drift diagnostics, and anti-tautological test verifications.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/code_freshness/models.py
"""

from enum import Enum
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class FreshnessState(str, Enum):
    """Three-state evaluation of runtime in-memory code vs on-disk script files."""

    FRESH = "fresh"  # Process started at or after on-disk code modification
    STALE = "stale"  # Disk script is newer than current process; running outdated bytecode
    INDETERMINATE = "indeterminate"  # Unverifiable (e.g. bundled binary, unreadable, virtual fs)


class IndeterminateReason(str, Enum):
    """Explicitly articulated cause when freshness cannot be conclusively judged."""

    NONE = "none"
    FILE_NOT_FOUND = "file_not_found"
    PERMISSION_DENIED = "permission_denied"
    VIRTUAL_OR_BUNDLED = "virtual_or_bundled_executable"
    CLOCK_DRIFT_DETECTED = "clock_drift_anomaly"
    DYNAMIC_EVAL_SOURCE = "dynamic_eval_or_in_memory_only"


class ModuleFreshnessEntry(BaseModel):
    """Freshness verification record for an individual critical code module or entry script."""

    module_name: str = Field(..., description="Python or script module identifier")
    file_path: str = Field(..., description="Absolute path on disk to module source file")
    process_start_time_ms: int = Field(..., ge=0, description="Process launch epoch timestamp in milliseconds")
    disk_mtime_ms: Optional[int] = Field(default=None, description="Source file mtime epoch timestamp in milliseconds")
    time_drift_seconds: Optional[float] = Field(
        default=None, description="disk_mtime - process_start_time (positive indicates stale process)"
    )
    state: FreshnessState = Field(..., description="fresh | stale | indeterminate")
    reason: IndeterminateReason = Field(default=IndeterminateReason.NONE, description="Explicit failure reason")
    remediation_hint: str = Field(default="", description="Operator guidance (e.g. drain & restart service)")


class RuntimeFreshnessReport(BaseModel):
    """Aggregated process-wide code freshness health inspection."""

    pid: int = Field(..., description="Operating system process ID")
    overall_state: FreshnessState = Field(..., description="Aggregate system freshness state")
    total_inspected_modules: int = Field(default=0, ge=0)
    stale_modules_count: int = Field(default=0, ge=0)
    fresh_modules_count: int = Field(default=0, ge=0)
    indeterminate_count: int = Field(default=0, ge=0)
    inspected_at_ms: int = Field(..., ge=0)
    details: List[ModuleFreshnessEntry] = Field(default_factory=list)
