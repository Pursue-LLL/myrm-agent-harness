# [INPUT]: ChatHeadShardSyncSuite, ContentShard, SchemaVersion, ShardAddress
# [OUTPUT]: test_chat_head_cas_publish_and_hash_diff_idempotency, test_lineage_chain_fork_detection_and_conflict_rejection, test_version_gate_major_rejection_and_minor_passthrough, test_min_reader_version_safety_floor_blocks_outdated_reader
# [POS]: tests/agent/context_management/test_chat_head_sync_suite.py

"""Comprehensive test suite for chat head pointer and immutable shard synchronization protocol.

Validates:
1. Lightweight mutable head pointer swapped via CAS and hash-diff idempotent shard persistence.
2. Cryptographic lineage chain parentHeadSha256 fork detection and conflict rejection (no seq comparisons).
3. Version gate admitting same-major schema evolution with forward passthrough and rejecting unsupported major.
4. minReaderVersion safety floor strictly blocking outdated readers on high-risk semantic changes.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.chat_head_sync import (
    AssembleResult,
    CasSyncResult,
    ChatHeadPointer,
    ChatHeadShardSyncSuite,
    ChatShardStorageEngine,
    ContentShard,
    SchemaVersion,
    ShardAddress,
    VersionGateResult,
    gate_chat_head_version,
)


def test_chat_head_cas_publish_and_hash_diff_idempotency() -> None:
    """Validate CAS-based head publishing, lightweight pointer footprint, and hash-diff deduplication."""
    suite = ChatHeadShardSyncSuite.create()
    chat_id = "chat_sess_001"
    schema_v1 = SchemaVersion(major=1, minor=0)

    # Initial publication with first shard
    shard1_data = b'{"seq": 1, "role": "user", "text": "Hello assistant"}'
    shard1 = ContentShard.create(
        data=shard1_data,
        record_count=1,
        first_seq=1,
        last_seq=1,
        first_record_id="rec_1",
        last_record_id="rec_1",
    )

    initial_pub = suite.publish_with_cas(
        chat_id=chat_id,
        shards=[shard1],
        expected_parent_head_sha256=None,
        schema_version=schema_v1,
        metadata={"title": "Greeting session"},
    )

    assert initial_pub.ok is True
    assert initial_pub.new_head_sha256 is not None
    assert initial_pub.new_shards_uploaded == 1
    head_v1_sha = initial_pub.new_head_sha256

    # Verify head pointer existence and addresses
    head_v1 = suite.get_head(chat_id)
    assert head_v1 is not None
    assert head_v1.chat_id == chat_id
    assert head_v1.parent_head_sha256 is None
    assert head_v1.head_sha256 == head_v1_sha
    assert len(head_v1.shard_addresses) == 1
    assert head_v1.shard_addresses[0].sha256 == shard1.address.sha256

    # Subsequent publication: append shard 2 while retaining shard 1
    shard2_data = b'{"seq": 2, "role": "assistant", "text": "Hello user, how may I assist?"}'
    shard2 = ContentShard.create(
        data=shard2_data,
        record_count=1,
        first_seq=2,
        last_seq=2,
        first_record_id="rec_2",
        last_record_id="rec_2",
    )

    append_pub = suite.publish_with_cas(
        chat_id=chat_id,
        shards=[shard1, shard2],
        expected_parent_head_sha256=head_v1_sha,
        schema_version=schema_v1,
        metadata={"title": "Greeting session"},
    )

    assert append_pub.ok is True
    assert append_pub.new_head_sha256 is not None
    assert append_pub.new_head_sha256 != head_v1_sha
    # Hash-diff verification: shard1 was already stored, so only shard2 counts as newly uploaded
    assert append_pub.new_shards_uploaded == 1
    head_v2_sha = append_pub.new_head_sha256

    head_v2 = suite.get_head(chat_id)
    assert head_v2 is not None
    assert head_v2.parent_head_sha256 == head_v1_sha
    assert len(head_v2.shard_addresses) == 2

    # Retry publication with identical state (idempotency convergence)
    retry_pub = suite.publish_with_cas(
        chat_id=chat_id,
        shards=[shard1, shard2],
        expected_parent_head_sha256=head_v1_sha,
        schema_version=schema_v1,
        metadata={"title": "Greeting session"},
    )
    # Since head advanced to head_v2, repeating with parent=head_v1 detects conflict
    assert retry_pub.ok is False
    assert retry_pub.fork_detected is True


def test_lineage_chain_fork_detection_and_conflict_rejection() -> None:
    """Validate parentHeadSha256 ancestry chain prevents sequence-number-based fork overwrites."""
    suite = ChatHeadShardSyncSuite.create()
    chat_id = "chat_sess_fork_test"
    schema_v1 = SchemaVersion(major=1, minor=1)

    # Base commit H0
    base_data = b'{"seq": 1, "text": "Base root turn"}'
    base_shard = ContentShard.create(base_data, record_count=1, first_seq=1, last_seq=1)

    res_base = suite.publish_with_cas(
        chat_id=chat_id,
        shards=[base_shard],
        expected_parent_head_sha256=None,
        schema_version=schema_v1,
    )
    assert res_base.ok is True
    h0_sha = res_base.new_head_sha256
    head_0 = suite.get_head(chat_id)
    assert head_0 is not None

    # Branch A advances to H1_A
    shard_a_data = b'{"seq": 2, "text": "Branch A edit"}'
    shard_a = ContentShard.create(shard_a_data, record_count=1, first_seq=2, last_seq=2)
    res_a = suite.publish_with_cas(
        chat_id=chat_id,
        shards=[base_shard, shard_a],
        expected_parent_head_sha256=h0_sha,
        schema_version=schema_v1,
    )
    assert res_a.ok is True
    head_a = suite.get_head(chat_id)
    assert head_a is not None

    # Concurrent Branch B tries to publish against H0 with higher seq numbers (e.g. seq=3,4,5)
    # Seq comparison would falsely let B overwrite A ("local seq is ahead").
    # The parentHeadSha256 CAS strictly rejects B!
    shard_b_data = b'{"seq": 5, "text": "Branch B high seq edit"}'
    shard_b = ContentShard.create(shard_b_data, record_count=1, first_seq=5, last_seq=5)
    res_b = suite.publish_with_cas(
        chat_id=chat_id,
        shards=[base_shard, shard_b],
        expected_parent_head_sha256=h0_sha,  # Stale parent! Current is head_a.head_sha256
        schema_version=schema_v1,
    )

    assert res_b.ok is False
    assert res_b.fork_detected is True
    assert "CAS collision" in (res_b.error_message or "")

    # Construct separate detached head for Branch B to verify fork divergence query
    suite_b = ChatHeadShardSyncSuite.create()
    res_b_isolated = suite_b.publish_with_cas(
        chat_id=chat_id,
        shards=[base_shard, shard_b],
        expected_parent_head_sha256=None,
        schema_version=schema_v1,
    )
    head_b = suite_b.get_head(chat_id)
    assert head_b is not None

    # Divergence detection confirms heads have disjoint paths
    assert suite.is_forked(head_a, head_b) is True


def test_version_gate_major_rejection_and_minor_passthrough() -> None:
    """Validate same-major forward passthrough and strict major reject boundary with 0 egress."""
    suite = ChatHeadShardSyncSuite.create()
    chat_id = "chat_sess_version_test"

    shard_data = b'{"seq": 1, "msg": "Forward-compatible message block"}'
    shard = ContentShard.create(shard_data, record_count=1, first_seq=1, last_seq=1)

    # Server published with schema version 1.6
    pub_res = suite.publish_with_cas(
        chat_id=chat_id,
        shards=[shard],
        expected_parent_head_sha256=None,
        schema_version=SchemaVersion(major=1, minor=6),
        min_reader_version=None,
    )
    assert pub_res.ok is True

    # Older reader running on 1.2 accessing 1.6 chat (same major, no min_reader_version floor)
    reader_v1_2 = SchemaVersion(major=1, minor=2)
    assemble_v1_2 = suite.fetch_and_assemble(chat_id=chat_id, reader_supports=reader_v1_2)

    assert assemble_v1_2.ok is True
    assert assemble_v1_2.shards_loaded == 1
    assert assemble_v1_2.total_bytes == len(shard_data)
    assert assemble_v1_2.assembled_records == [shard_data]

    # Reader running on incompatible major 2.0 accessing 1.6 chat
    reader_v2_0 = SchemaVersion(major=2, minor=0)
    assemble_v2_0 = suite.fetch_and_assemble(chat_id=chat_id, reader_supports=reader_v2_0)

    assert assemble_v2_0.ok is False
    assert assemble_v2_0.gate_reason == "unsupported-major"
    # Zero egress guarantee: unreadable chat incurs 0 shard loading
    assert assemble_v2_0.shards_loaded == 0
    assert assemble_v2_0.total_bytes == 0
    assert "not readable by a reader on major 2" in (assemble_v2_0.error_message or "")


def test_min_reader_version_safety_floor_blocks_outdated_reader() -> None:
    """Validate minReaderVersion escape hatch blocks older readers before fetching shards."""
    suite = ChatHeadShardSyncSuite.create()
    chat_id = "chat_sess_security_action"

    sensitive_shard_data = b'{"seq": 1, "action": "autonomous_fund_transfer_authorized"}'
    shard = ContentShard.create(sensitive_shard_data, record_count=1, first_seq=1, last_seq=1)

    # Publisher stamps min_reader_version=1.5 because older readers would misinterpret transfer
    pub_res = suite.publish_with_cas(
        chat_id=chat_id,
        shards=[shard],
        expected_parent_head_sha256=None,
        schema_version=SchemaVersion(major=1, minor=6),
        min_reader_version=SchemaVersion(major=1, minor=5),
    )
    assert pub_res.ok is True

    # Reader on 1.3 is below minimum floor (1.5) -> Rejected with 0 egress
    outdated_reader = SchemaVersion(major=1, minor=3)
    res_outdated = suite.fetch_and_assemble(chat_id=chat_id, reader_supports=outdated_reader)

    assert res_outdated.ok is False
    assert res_outdated.gate_reason == "reader-below-minimum"
    assert res_outdated.shards_loaded == 0
    assert res_outdated.total_bytes == 0
    assert "requires a reader on 1.5 or newer" in (res_outdated.error_message or "")

    # Reader on 1.5 meets the floor -> Admitted
    competent_reader = SchemaVersion(major=1, minor=5)
    res_competent = suite.fetch_and_assemble(chat_id=chat_id, reader_supports=competent_reader)

    assert res_competent.ok is True
    assert res_competent.shards_loaded == 1
    assert res_competent.total_bytes == len(sensitive_shard_data)
    assert res_competent.assembled_records == [sensitive_shard_data]
