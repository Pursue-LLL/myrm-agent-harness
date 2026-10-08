# [INPUT]: ArchiveTier, ColdArchiveRecord, ConversationArchiveShareConfig, ConversationShareableSnapshotAndTieredColdArchiveSuite, SanitizedShareMessage, SanitizedSnapshotExporter, ShareAccessPolicy, ShareVerificationResult, ShareableSnapshotManifest, SignedShareGateway, TieredColdStorageArchiver
# [OUTPUT]: test_conversation_shareable_snapshot_suite.py
# [POS]: tests/agent/context_management/test_conversation_shareable_snapshot_suite.py

"""Comprehensive unit tests for ConversationShareableSnapshotAndTieredColdArchiveSuite.

Verifies:
1. Regex-driven redaction of credentials (API keys, GitHub tokens, AWS keys, passwords).
2. HMAC-SHA256 tamper-evident verification detecting modified content or titles.
3. Ephemeral share TTL expiration, validation checks, and instant link revocation.
4. Tiered cold session hibernation with high-ratio lossless compression and SHA-256 integrity checks.
5. Instant lossless session wakeup reconstructing original payloads bit-for-bit.
6. Offline cold archive index search without payload decompression.
7. End-to-end facade lifecycle orchestration.
"""

from __future__ import annotations

import json
import pytest

from myrm_agent_harness.agent.context_management.conversation_archive_share import (
    ArchiveTier,
    ColdArchiveRecord,
    ConversationArchiveShareConfig,
    ConversationShareableSnapshotAndTieredColdArchiveSuite,
    SanitizedShareMessage,
    SanitizedSnapshotExporter,
    ShareAccessPolicy,
    ShareVerificationResult,
    ShareableSnapshotManifest,
    SignedShareGateway,
    TieredColdStorageArchiver,
)


def test_credentials_redaction_and_sanitization() -> None:
    """Verifies that API keys, passwords, and tokens are scrubbed from content and tool calls."""
    exporter = SanitizedSnapshotExporter()
    t0 = 1000.0

    raw_messages = [
        {
            "role": "user",
            "content": "Please connect using sk-proj1234567890123456789012345 and password='super_secret_pass'.",
            "timestamp": t0,
        },
        {
            "role": "assistant",
            "content": "Here is the GitHub token ghp_123456789012345678901234567890123456 and AWS AKIAIOSFODNN7EXAMPLE.",
            "timestamp": t0 + 1.0,
            "tool_calls": ["curl -H 'Bearer tok_abcdef123456789012345' https://api.example.com"],
        },
    ]

    manifest = exporter.export_snapshot(
        session_id="session-001",
        title="Debug Secrets Session",
        raw_messages=raw_messages,
        timestamp=t0,
    )

    assert manifest.redactions_count == 5
    # Verify user message
    user_msg = manifest.messages[0]
    assert "sk-" not in user_msg.content
    assert "super_secret_pass" not in user_msg.content
    assert "[REDACTED_SECRET]" in user_msg.content

    # Verify assistant message & tool calls
    asst_msg = manifest.messages[1]
    assert "ghp_" not in asst_msg.content
    assert "AKIA" not in asst_msg.content
    assert len(asst_msg.sanitized_tool_calls) == 1
    assert "Bearer" not in asst_msg.sanitized_tool_calls[0]
    assert "[REDACTED_SECRET]" in asst_msg.sanitized_tool_calls[0]


def test_hmac_tamper_evident_verification() -> None:
    """Verifies that any modification to messages or title fails HMAC verification."""
    config = ConversationArchiveShareConfig(signing_secret="secure-test-signing-key")
    exporter = SanitizedSnapshotExporter(config)
    gateway = SignedShareGateway(exporter)
    t0 = 2000.0

    raw = [{"role": "user", "content": "Initial message", "timestamp": t0}]
    manifest = exporter.export_snapshot("sess-1", "Original Title", raw, timestamp=t0)
    gateway.register_snapshot(manifest)

    # 1. Untampered manifest succeeds
    result_ok = gateway.verify_and_access(manifest.share_id, timestamp=t0 + 10.0)
    assert result_ok.is_valid is True
    assert result_ok.is_expired is False
    assert result_ok.manifest is not None

    # 2. Tampered manifest (title changed) fails verification
    tampered_manifest = ShareableSnapshotManifest(
        share_id=manifest.share_id,
        session_id=manifest.session_id,
        title="Tampered Malicious Title",
        messages=manifest.messages,
        signature=manifest.signature,
        created_at=manifest.created_at,
        expires_at=manifest.expires_at,
        redactions_count=manifest.redactions_count,
        policy=manifest.policy,
    )
    gateway.register_snapshot(tampered_manifest)

    result_tampered = gateway.verify_and_access(manifest.share_id, timestamp=t0 + 10.0)
    assert result_tampered.is_valid is False
    assert "Signature mismatch" in result_tampered.reason


def test_ephemeral_ttl_expiration_and_revocation() -> None:
    """Verifies snapshot TTL expiry and immediate revocation."""
    exporter = SanitizedSnapshotExporter()
    gateway = SignedShareGateway(exporter)
    t0 = 3000.0

    raw = [{"role": "user", "content": "Short lived share", "timestamp": t0}]
    # 60s TTL
    manifest = exporter.export_snapshot("sess-ttl", "Expiring Share", raw, ttl_seconds=60.0, timestamp=t0)
    gateway.register_snapshot(manifest)

    # Valid before expiration (t0 + 50s)
    res_before = gateway.verify_and_access(manifest.share_id, timestamp=t0 + 50.0)
    assert res_before.is_valid is True

    # Expired after 60s (t0 + 65s)
    res_after = gateway.verify_and_access(manifest.share_id, timestamp=t0 + 65.0)
    assert res_after.is_valid is False
    assert res_after.is_expired is True
    assert "expired" in res_after.reason.lower()

    # Instant revocation
    assert gateway.revoke_share(manifest.share_id) is True
    res_revoked = gateway.verify_and_access(manifest.share_id, timestamp=t0 + 50.0)
    assert res_revoked.is_valid is False
    assert "not found" in res_revoked.reason.lower()


def test_tiered_cold_hibernation_and_lossless_wakeup() -> None:
    """Verifies lossless compression during hibernation and bit-for-bit restoration upon wakeup."""
    archiver = TieredColdStorageArchiver(ConversationArchiveShareConfig(enable_compression=True))
    session_id = "sess-large-task"
    t0 = 4000.0

    # Build substantial session payload
    conversation_turns = [
        {"turn": i, "user": f"Query number {i} with code sample", "output": f"Result {i} " * 20}
        for i in range(100)
    ]
    raw_json = json.dumps(conversation_turns)
    raw_size = len(raw_json.encode("utf-8"))

    # 1. Hibernate session
    record = archiver.hibernate_session(
        session_id=session_id,
        title="Big Task Session",
        session_payload_json=raw_json,
        total_messages=200,
        total_tokens=15000,
        summary_excerpt="Summary of 100 queries regarding code samples",
        timestamp=t0,
    )

    assert record.tier == ArchiveTier.COLD_HIBERNATED
    assert record.total_messages == 200
    compressed_size = len(record.compressed_payload_bytes)
    assert compressed_size < raw_size
    # Compression ratio should exceed 70% for repetitive text
    savings_ratio = (raw_size - compressed_size) / raw_size
    assert savings_ratio > 0.70

    # 2. Instant wakeup
    active_record, restored_json = archiver.wake_session(session_id)
    assert active_record.tier == ArchiveTier.ACTIVE
    assert restored_json == raw_json  # Bit-for-bit exact match
    restored_turns = json.loads(restored_json)
    assert len(restored_turns) == 100


def test_offline_cold_archive_keyword_search() -> None:
    """Verifies fast keyword lookup over titles and summaries without full decompression."""
    archiver = TieredColdStorageArchiver()

    archiver.hibernate_session("s1", "Postgres Migration Plan", "{}", 10, 1000, summary_excerpt="Schema refactor")
    archiver.hibernate_session("s2", "Frontend React Redesign", "{}", 20, 2000, summary_excerpt="Tailwind components")
    archiver.hibernate_session("s3", "Redis Cache Optimization", "{}", 15, 1500, summary_excerpt="Postgres fallback")

    # Search query "postgres" -> matches s1 (title) and s3 (excerpt)
    matches_pg = archiver.search_cold_archives("postgres")
    assert len(matches_pg) == 2
    matched_ids = {r.session_id for r in matches_pg}
    assert matched_ids == {"s1", "s3"}

    # Search query "react" -> matches s2
    matches_react = archiver.search_cold_archives("react")
    assert len(matches_react) == 1
    assert matches_react[0].session_id == "s2"


def test_facade_end_to_end_lifecycle() -> None:
    """Verifies high-level facade coordinating sharing, cold archiving, and session restoration."""
    suite = ConversationShareableSnapshotAndTieredColdArchiveSuite(
        ConversationArchiveShareConfig(signing_secret="facade-test-key")
    )
    session_id = "sess-facade-007"
    t0 = 5000.0

    raw_msgs = [
        {"role": "user", "content": "How to deploy to k8s with sk-1234567890123456789012345?", "timestamp": t0},
        {"role": "assistant", "content": "Deploying using kubectl apply -f manifest.yaml", "timestamp": t0 + 1.0},
    ]

    # 1. Create and verify share
    manifest = suite.create_shareable_snapshot(
        session_id=session_id,
        title="Kubernetes Deployment Guide",
        raw_messages=raw_msgs,
        ttl_seconds=3600.0,
        timestamp=t0,
    )
    assert manifest.redactions_count == 1
    assert suite.total_shares_count == 1

    access_res = suite.verify_and_access_share(manifest.share_id, timestamp=t0 + 10.0)
    assert access_res.is_valid is True

    # 2. Hibernate session into cold tier
    archive_rec = suite.hibernate_session(
        session_id=session_id,
        title="Kubernetes Deployment Guide",
        session_payload_json=json.dumps(raw_msgs),
        total_messages=2,
        total_tokens=450,
        summary_excerpt="K8s deployment instructions and manifests",
        timestamp=t0 + 2.0,
    )
    assert archive_rec.tier == ArchiveTier.COLD_HIBERNATED
    assert suite.total_archived_count == 1

    # 3. Search cold archives
    results = suite.search_cold_archives("kubernetes")
    assert len(results) == 1
    assert results[0].session_id == session_id

    # 4. Wake session
    restored_record, restored_content = suite.wake_session(session_id)
    assert restored_record.tier == ArchiveTier.ACTIVE
    assert "kubectl" in restored_content

    # 5. Revoke share & delete archive
    assert suite.revoke_share(manifest.share_id) is True
    assert suite.total_shares_count == 0
    assert suite.delete_archive(session_id) is True
    assert suite.total_archived_count == 0
