# [POS]: myrm_agent_harness/toolkits/memory/drift_defense/types.py
# [INPUT]: pydantic, enum
# [OUTPUT]: DriftType, MemoryDriftFinding, DriftCheckRequest, DriftCheckResult, DriftDefenseConfig
"""Type definitions for ground truth priority and memory drift stale defense.

Models drift classifications, inspection results, and prompt decoration metadata.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class DriftType(StrEnum):
    """Classification of drift detected between memory statement and ground truth."""

    FILE_NOT_FOUND = "file_not_found"
    FILE_CONTENT_DRIFT = "file_content_drift"
    SYMBOL_NOT_FOUND = "symbol_not_found"
    CONFIG_CHANGED = "config_changed"


class MemoryDriftFinding(BaseModel):
    """Detailed finding of an individual drift discrepancy."""

    model_config = ConfigDict(extra="forbid")

    drift_type: DriftType = Field(..., description="Type of drift detected")
    reference_target: str = Field(..., description="Target file path, config key, or symbol name")
    detail: str = Field(..., description="Human-readable explanation of the discrepancy")
    is_stale: bool = Field(default=True, description="Whether this finding warrants stale deprecation")


class DriftCheckRequest(BaseModel):
    """Request payload to evaluate candidate memory for physical world drift."""

    model_config = ConfigDict(extra="forbid")

    memory_id: str = Field(..., description="Unique memory identifier")
    content: str = Field(..., min_length=1, description="Memory text content to inspect")
    workspace_root: Path | str = Field(..., description="Active workspace root directory")
    recorded_path: str | None = Field(default=None, description="Explicit file path bound to memory if any")
    recorded_symbol: str | None = Field(default=None, description="Explicit symbol bound to memory if any")


class DriftCheckResult(BaseModel):
    """Result of ground truth drift evaluation."""

    model_config = ConfigDict(extra="forbid")

    memory_id: str = Field(..., description="Evaluated memory identifier")
    is_drifted: bool = Field(..., description="True if any drift discrepancy was confirmed")
    confidence_penalty: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence deduction applied (0.0 means pristine, 0.8+ means severely stale)",
    )
    findings: list[MemoryDriftFinding] = Field(
        default_factory=list,
        description="List of detected drift findings",
    )
    decorated_content: str = Field(
        ...,
        description="Memory text with stale warning prefix injected if drifted",
    )


class DriftDefenseConfig(BaseModel):
    """Configuration for ground truth drift defense."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(default=True, description="Whether drift checking is active")
    stale_confidence_penalty: float = Field(
        default=0.6,
        ge=0.0,
        le=1.0,
        description="Confidence penalty deducted when drift is confirmed",
    )
    stale_warning_template: str = Field(
        default="[⚠️ 过时警告: 对应业务文件或配置已发生演进，请以当前最新状态为准]\n{content}",
        description="Prompt template applied when memory has drifted from ground truth",
    )
    cache_ttl_seconds: int = Field(default=30, ge=1, le=3600, description="LRU cache TTL for file checks")
