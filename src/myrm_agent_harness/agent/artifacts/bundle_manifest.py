"""Deliverable Bundle Manifest schema and utilities.

Defines the contract for grouping multi-file agent task outputs (documents, spreadsheets,
visual assets, fact-check sheets, schedules) into an organized deliverable bundle with metadata.

[INPUT]
- (none)

[OUTPUT]
- DeliverableItem: class — Item within a deliverable bundle
- DeliverableManifest: class — Structured manifest describing the complete deliverable package
- build_deliverable_manifest: function — Helper to construct a manifest from generated file metadata

[POS]
Harness Layer — Artifact Bundle Manifest contract SSOT.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import time
from typing import Any
from uuid import uuid4


class DeliverableCategory(str, Enum):
    """Category classification for bundle items."""

    STRATEGY = "strategy"
    COPYWRITING = "copywriting"
    VISUAL = "visual"
    DATA_SHEET = "data_sheet"
    FACT_CHECK = "fact_check"
    SCHEDULE = "schedule"
    CODE = "code"
    OTHER = "other"


class DeliverableStatus(str, Enum):
    """Verification and distribution readiness status."""

    DRAFT = "draft"
    VERIFIED = "verified"
    READY_FOR_DISTRIBUTION = "ready_for_distribution"


# Standard folder names by category
CATEGORY_DIRECTORY_MAPPING: dict[DeliverableCategory, str] = {
    DeliverableCategory.STRATEGY: "01_strategy_and_overview",
    DeliverableCategory.COPYWRITING: "02_copywriting_and_content",
    DeliverableCategory.VISUAL: "03_visual_and_media",
    DeliverableCategory.DATA_SHEET: "04_data_and_sheets",
    DeliverableCategory.FACT_CHECK: "05_fact_check_and_audit",
    DeliverableCategory.SCHEDULE: "06_schedule_and_plans",
    DeliverableCategory.CODE: "07_code_and_scripts",
    DeliverableCategory.OTHER: "08_misc_deliverables",
}


@dataclass
class DeliverableItem:
    """An individual artifact item in a deliverable bundle."""

    id: str
    filename: str
    relative_path: str
    category: DeliverableCategory = DeliverableCategory.OTHER
    platform: str | None = None
    content_type: str = "application/octet-stream"
    size_bytes: int = 0
    sha256_hash: str = ""
    status: DeliverableStatus = DeliverableStatus.READY_FOR_DISTRIBUTION
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["category"] = self.category.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeliverableItem:
        category_raw = data.get("category", DeliverableCategory.OTHER.value)
        try:
            category = DeliverableCategory(category_raw)
        except ValueError:
            category = DeliverableCategory.OTHER

        status_raw = data.get("status", DeliverableStatus.READY_FOR_DISTRIBUTION.value)
        try:
            status = DeliverableStatus(status_raw)
        except ValueError:
            status = DeliverableStatus.READY_FOR_DISTRIBUTION

        return cls(
            id=str(data.get("id", "")),
            filename=str(data.get("filename", "")),
            relative_path=str(data.get("relative_path", "")),
            category=category,
            platform=data.get("platform"),
            content_type=str(data.get("content_type", "application/octet-stream")),
            size_bytes=int(data.get("size_bytes", 0)),
            sha256_hash=str(data.get("sha256_hash", "")),
            status=status,
            description=str(data.get("description", "")),
        )


@dataclass
class DeliverableManifest:
    """Top-level manifest describing an entire multi-file deliverable package."""

    bundle_id: str = field(default_factory=lambda: str(uuid4()))
    title: str = "Deliverable Package"
    description: str = ""
    agent_id: str | None = None
    goal_id: str | None = None
    created_at: float = field(default_factory=time.time)
    items: list[DeliverableItem] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "title": self.title,
            "description": self.description,
            "agent_id": self.agent_id,
            "goal_id": self.goal_id,
            "created_at": self.created_at,
            "items": [item.to_dict() for item in self.items],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeliverableManifest:
        items_raw = data.get("items", [])
        items = [
            DeliverableItem.from_dict(item)
            for item in items_raw
            if isinstance(item, dict)
        ]
        return cls(
            bundle_id=str(data.get("bundle_id", str(uuid4()))),
            title=str(data.get("title", "Deliverable Package")),
            description=str(data.get("description", "")),
            agent_id=data.get("agent_id"),
            goal_id=data.get("goal_id"),
            created_at=float(data.get("created_at", time.time())),
            items=items,
            metadata=dict(data.get("metadata", {})),
        )


def infer_item_category(filename: str) -> DeliverableCategory:
    """Infer deliverable category from filename conventions and extension."""
    lower = filename.lower()
    if any(k in lower for k in ("fact_check", "factcheck", "verification", "audit")):
        return DeliverableCategory.FACT_CHECK
    if any(k in lower for k in ("schedule", "calendar", "timeline", "plan_7days")):
        return DeliverableCategory.SCHEDULE
    if any(k in lower for k in ("strategy", "proposal", "brief", "summary", "report")):
        return DeliverableCategory.STRATEGY
    if any(
        k in lower
        for k in (
            "wechat",
            "xhs",
            "xiaohongshu",
            "douyin",
            "script",
            "copy",
            "article",
            "post",
        )
    ):
        return DeliverableCategory.COPYWRITING
    if lower.endswith(
        (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".mp4", ".mp3", ".wav")
    ):
        return DeliverableCategory.VISUAL
    if lower.endswith((".xlsx", ".xls", ".csv")):
        return DeliverableCategory.DATA_SHEET
    if lower.endswith((".py", ".ts", ".js", ".sh", ".sql", ".rs", ".go")):
        return DeliverableCategory.CODE
    return DeliverableCategory.OTHER
