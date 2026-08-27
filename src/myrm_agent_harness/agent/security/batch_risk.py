"""Batch risk evaluation and dual insurance policy check for approval queues.

Pure deterministic functions (Layer 4/5 security domain) for batch tool risk classification.
Zero I/O, zero external dependencies, trivially testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Sequence


class BatchItemRiskLevel(StrEnum):
    SAFE = "safe"
    MODERATE = "moderate"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class BatchApprovalItem:
    """Input contract for batch risk evaluation."""

    item_id: str
    action_type: str
    tool_name: str
    severity: str = "warning"
    reason: str | None = None
    payload: dict[str, object] = field(default_factory=dict)
    is_smart_denied: bool = False
    is_high_risk: bool = False
    hide_allow_always: bool = False


@dataclass(frozen=True, slots=True)
class BatchRiskItemDetail:
    """Detailed risk metadata for a single item in a batch."""

    item_id: str
    action_type: str
    tool_name: str
    risk_level: BatchItemRiskLevel
    risk_reason: str


@dataclass(frozen=True, slots=True)
class BatchRiskReport:
    """Aggregate risk report for a batch of approval items."""

    has_high_risk: bool
    total_count: int
    high_risk_count: int
    safe_count: int
    high_risk_items: tuple[BatchRiskItemDetail, ...]
    safe_item_ids: tuple[str, ...]
    all_item_ids: tuple[str, ...]


def _classify_single_item(item: BatchApprovalItem) -> tuple[BatchItemRiskLevel, str]:
    """Classify the risk level of a single approval item."""
    if item.is_smart_denied:
        return BatchItemRiskLevel.HIGH, item.reason or "Security reviewer smart-denied action"

    if item.is_high_risk or item.hide_allow_always:
        return BatchItemRiskLevel.HIGH, item.reason or "High-risk escalation / mutation operation"

    if item.severity.lower() in ("critical", "high", "error"):
        return BatchItemRiskLevel.HIGH, item.reason or f"Critical/High severity action ({item.severity})"

    # Check payload reviewConfigs if provided
    review_configs = item.payload.get("reviewConfigs")
    if isinstance(review_configs, list):
        for cfg in review_configs:
            if isinstance(cfg, dict):
                if cfg.get("smartDenied") or cfg.get("hideAllowAlways"):
                    return BatchItemRiskLevel.HIGH, item.reason or "High-risk review configuration detected"

    # Action type inspection
    act = item.action_type.lower()
    if act in ("delete_file", "execute_sql_destructive", "privilege_escalation", "system_reboot"):
        return BatchItemRiskLevel.HIGH, f"Destructive action type: {item.action_type}"

    # Tool name inspection
    tool = item.tool_name.lower()
    if any(k in tool for k in ("danger", "destroy", "drop_db", "wipe")):
        return BatchItemRiskLevel.HIGH, f"High-risk tool name: {item.tool_name}"

    return BatchItemRiskLevel.SAFE, "Standard safe / approved action"


def classify_batch_approval_risk(items: Sequence[BatchApprovalItem]) -> BatchRiskReport:
    """Evaluate aggregate risk for a batch of approval items.

    Returns a BatchRiskReport with structured high-risk items and safe item IDs.
    """
    high_risk_details: list[BatchRiskItemDetail] = []
    safe_ids: list[str] = []
    all_ids: list[str] = []

    for item in items:
        all_ids.append(item.item_id)
        level, reason = _classify_single_item(item)
        if level == BatchItemRiskLevel.HIGH:
            high_risk_details.append(
                BatchRiskItemDetail(
                    item_id=item.item_id,
                    action_type=item.action_type,
                    tool_name=item.tool_name,
                    risk_level=level,
                    risk_reason=reason,
                )
            )
        else:
            safe_ids.append(item.item_id)

    return BatchRiskReport(
        has_high_risk=len(high_risk_details) > 0,
        total_count=len(items),
        high_risk_count=len(high_risk_details),
        safe_count=len(safe_ids),
        high_risk_items=tuple(high_risk_details),
        safe_item_ids=tuple(safe_ids),
        all_item_ids=tuple(all_ids),
    )


__all__ = [
    "BatchApprovalItem",
    "BatchItemRiskLevel",
    "BatchRiskItemDetail",
    "BatchRiskReport",
    "classify_batch_approval_risk",
]
