"""Deliverable Bundle Manifest alias and forwarder to core contract.

[INPUT]
- myrm_agent_harness.core.artifacts.manifest (POS: Standard manifest SSOT)

[OUTPUT]
- DeliverableCategory, DeliverableStatus, DeliverableItem, DeliverableManifest, CATEGORY_DIRECTORY_MAPPING, infer_item_category

[POS]
Harness Layer — Alias to core artifacts manifest SSOT to ensure unified contract.
"""

from __future__ import annotations

from myrm_agent_harness.core.artifacts.manifest import (
    CATEGORY_DIRECTORY_MAPPING,
    DeliverableCategory,
    DeliverableItem,
    DeliverableManifest,
    DeliverableStatus,
    infer_item_category,
)

__all__ = [
    "CATEGORY_DIRECTORY_MAPPING",
    "DeliverableCategory",
    "DeliverableItem",
    "DeliverableManifest",
    "DeliverableStatus",
    "infer_item_category",
]
