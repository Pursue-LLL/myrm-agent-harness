"""Unit tests for Agent Ownership Portable Export and No Lock-in Migration Suite.

Verifies cross-engine portable context bundle packaging, credential redaction,
SHA-256 tamper-evident integrity receipts, selective scope filtering, and round-trip JSON serialization.
"""

from __future__ import annotations

import json
import pytest

from myrm_agent_harness.agent.context_management import (
    AgentOwnershipPortableExportAndNoLockInSuite,
    ContextArtifactKind,
    ExportIntegrityReceipt,
    ExportScope,
    PortableBundleBuilder,
    PortableContextBundle,
    PortableContextItem,
)


def _sample_context_items() -> list[PortableContextItem]:
    return [
        PortableContextItem(
            item_id="sess-001",
            kind=ContextArtifactKind.SESSION,
            title="Database Migration Refactoring",
            content="User discussed migrating schema to PostgreSQL with api_key='sk-live12345678901234567890'.",
            metadata={"model": "claude-3-7-sonnet"},
            created_at_iso="2026-10-08T00:00:00Z",
        ),
        PortableContextItem(
            item_id="sess-002",
            kind=ContextArtifactKind.SESSION,
            title="Frontend UI Implementation",
            content="User implemented React modal with Tailwind CSS.",
            metadata={"model": "deepseek-chat"},
            created_at_iso="2026-10-08T01:00:00Z",
        ),
        PortableContextItem(
            item_id="mem-001",
            kind=ContextArtifactKind.MEMORY,
            title="User Preference - Language",
            content="User prefers Python for backend and TypeScript for frontend.",
            metadata={"category": "preference"},
            created_at_iso="2026-10-08T02:00:00Z",
        ),
        PortableContextItem(
            item_id="skill-001",
            kind=ContextArtifactKind.SKILL,
            title="Deploy Script Runner",
            content="Runs container deployment using password='supersecretpass123'.",
            metadata={"runtime": "bash"},
            created_at_iso="2026-10-08T03:00:00Z",
        ),
        PortableContextItem(
            item_id="cron-001",
            kind=ContextArtifactKind.CRON_TASK,
            title="Hourly Health Monitor",
            content="Checks endpoint /api/health every hour with Bearer abcdef123456789.",
            metadata={"schedule": "0 * * * *"},
            created_at_iso="2026-10-08T04:00:00Z",
        ),
    ]


def test_portable_bundle_builder_filtering_and_redaction() -> None:
    """Verify selective scope filtering and credential redaction."""
    builder = PortableBundleBuilder()
    items = _sample_context_items()

    # Scope: only sessions and memories, target session sess-001 only, with redaction
    scope = ExportScope(
        target_session_ids=["sess-001"],
        included_kinds=[ContextArtifactKind.SESSION, ContextArtifactKind.MEMORY],
        redact_secrets=True,
    )

    bundle = builder.build_bundle(raw_items=items, scope=scope)
    assert len(bundle.items) == 2
    item_ids = {it.item_id for it in bundle.items}
    assert item_ids == {"sess-001", "mem-001"}

    # Verify redaction
    sess_item = next(it for it in bundle.items if it.item_id == "sess-001")
    assert "sk-live12345678901234567890" not in sess_item.content
    assert "[REDACTED_SECRET]" in sess_item.content
    assert bundle.receipt.redaction_applied is True
    assert bundle.receipt.kind_counts == {"session": 1, "memory": 1}


def test_cryptographic_integrity_verification_and_tamper_detection() -> None:
    """Verify SHA-256 integrity check and tamper detection."""
    suite = AgentOwnershipPortableExportAndNoLockInSuite()
    items = _sample_context_items()

    bundle = suite.export_bundle(items=items)
    assert bundle.receipt.total_items == 5
    assert len(bundle.receipt.sha256_checksum) == 64

    # Legitimate bundle passes integrity check
    assert suite.verify_bundle_integrity(bundle) is True

    # Tampered bundle fails integrity check
    tampered_items = list(bundle.items)
    tampered_items[0] = PortableContextItem(
        item_id=tampered_items[0].item_id,
        kind=tampered_items[0].kind,
        title=tampered_items[0].title,
        content="Tampered illegitimate payload!",
        metadata=tampered_items[0].metadata,
        created_at_iso=tampered_items[0].created_at_iso,
    )
    tampered_bundle = PortableContextBundle(
        schema_version=bundle.schema_version,
        receipt=bundle.receipt,
        items=tampered_items,
        handoff_guide_markdown=bundle.handoff_guide_markdown,
    )
    assert suite.verify_bundle_integrity(tampered_bundle) is False


def test_suite_json_serialization_and_deserialization_fidelity() -> None:
    """Verify round-trip JSON serialization, handoff guide, and telemetry metrics."""
    suite = AgentOwnershipPortableExportAndNoLockInSuite()
    items = _sample_context_items()

    bundle = suite.export_bundle(items=items)
    json_output = suite.serialize_bundle_to_json(bundle)
    assert isinstance(json_output, str)
    assert "schema_version" in json_output
    assert "proof_statement" in json_output

    # Deserialize back
    restored_bundle = suite.deserialize_bundle_from_json(json_output)
    assert restored_bundle.schema_version == bundle.schema_version
    assert restored_bundle.receipt.receipt_id == bundle.receipt.receipt_id
    assert restored_bundle.receipt.sha256_checksum == bundle.receipt.sha256_checksum
    assert len(restored_bundle.items) == len(bundle.items)
    assert suite.verify_bundle_integrity(restored_bundle) is True

    # Handoff guide check
    assert "# Portable Context Layer Handoff Guide" in bundle.handoff_guide_markdown
    assert bundle.receipt.receipt_id in bundle.handoff_guide_markdown

    # Telemetry metrics
    stats = suite.get_aggregate_stats()
    assert stats["export_bundles_generated"] == 1
    assert stats["total_items_exported"] == 5
