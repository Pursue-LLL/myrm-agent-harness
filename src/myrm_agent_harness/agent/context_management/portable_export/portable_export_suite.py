"""Agent Ownership Portable Export and No Lock-in Migration Suite master class.

Coordinates cross-engine portable bundle exports, cryptographic integrity audits,
selective scope parsing, and JSON serialization.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Sequence

from .portable_bundle_builder import PortableBundleBuilder
from .portable_export_types import (
    ContextArtifactKind,
    ExportIntegrityReceipt,
    ExportScope,
    PortableContextBundle,
    PortableContextItem,
)


class AgentOwnershipPortableExportAndNoLockInSuite:
    """Master suite governing standard context layer export, portability, and anti-vendor-lockin."""

    def __init__(self) -> None:
        self._builder = PortableBundleBuilder()
        self._export_count = 0
        self._exported_items_total = 0

    @property
    def builder(self) -> PortableBundleBuilder:
        """Access underlying bundle builder engine."""
        return self._builder

    def export_bundle(
        self,
        items: Sequence[PortableContextItem],
        scope: ExportScope | None = None,
    ) -> PortableContextBundle:
        """Build and cryptographically seal a standard portable context bundle."""
        bundle = self._builder.build_bundle(raw_items=items, scope=scope)
        self._export_count += 1
        self._exported_items_total += bundle.receipt.total_items
        return bundle

    def verify_bundle_integrity(self, bundle: PortableContextBundle) -> bool:
        """Verify that the bundle contents match the cryptographically recorded SHA-256 receipt."""
        computed = self._builder.calculate_checksum(bundle.items)
        return computed == bundle.receipt.sha256_checksum

    def serialize_bundle_to_json(self, bundle: PortableContextBundle) -> str:
        """Serialize a portable bundle into standard formatted JSON."""
        bundle_dict = {
            "schema_version": bundle.schema_version,
            "receipt": asdict(bundle.receipt),
            "items": [
                {
                    "item_id": item.item_id,
                    "kind": item.kind.value,
                    "title": item.title,
                    "content": item.content,
                    "metadata": item.metadata,
                    "created_at_iso": item.created_at_iso,
                }
                for item in bundle.items
            ],
            "handoff_guide_markdown": bundle.handoff_guide_markdown,
        }
        return json.dumps(bundle_dict, indent=2, ensure_ascii=False)

    def deserialize_bundle_from_json(self, json_str: str) -> PortableContextBundle:
        """Parse serialized JSON back into strongly typed PortableContextBundle."""
        data = json.loads(json_str)
        receipt_data = data["receipt"]
        receipt = ExportIntegrityReceipt(
            receipt_id=receipt_data["receipt_id"],
            exported_at_iso=receipt_data["exported_at_iso"],
            schema_version=receipt_data["schema_version"],
            total_items=receipt_data["total_items"],
            kind_counts=dict(receipt_data["kind_counts"]),
            sha256_checksum=receipt_data["sha256_checksum"],
            redaction_applied=receipt_data["redaction_applied"],
            proof_statement=receipt_data["proof_statement"],
        )

        items = [
            PortableContextItem(
                item_id=raw["item_id"],
                kind=ContextArtifactKind(raw["kind"]),
                title=raw["title"],
                content=raw["content"],
                metadata=dict(raw.get("metadata", {})),
                created_at_iso=raw.get("created_at_iso", ""),
            )
            for raw in data.get("items", [])
        ]

        return PortableContextBundle(
            schema_version=data.get("schema_version", self._builder.SCHEMA_VERSION),
            receipt=receipt,
            items=items,
            handoff_guide_markdown=data.get("handoff_guide_markdown", ""),
        )

    def get_aggregate_stats(self) -> dict[str, int]:
        """Telemetry reporting total export invocations and processed items."""
        return {
            "export_bundles_generated": self._export_count,
            "total_items_exported": self._exported_items_total,
        }
