"""[POS]: tests/unit/toolkits/memory/test_revocable_provenance_suite.py
[INPUT]: Isolated tmp_path directory, test sessions, messages, and dream cycles.
[OUTPUT]: Unit tests verifying provenance metadata, bidirectional source query, atomic memory forget, tombstone exclusions, and dream diary recording.
"""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.toolkits.memory import (
    DreamDiaryRecorder,
    ProvenanceMemoryStore,
    ProvenanceMetadata,
    ProvenanceQualifiedMemory,
    RevocableForgetEngine,
)


def test_provenance_memory_store_and_bidirectional_lookup(tmp_path: Path) -> None:
    """Verifies memory persistence, source linkage, and bidirectional lookup by session and message."""
    store = ProvenanceMemoryStore(storage_dir=tmp_path / "memory_store")

    # 1. Create two memories tied to a specific session turn
    meta1 = ProvenanceMetadata(
        session_id="sess_alpha_101",
        message_id="msg_001",
        turn_index=2,
        quote_snippet="Always prefer pytest-asyncio for testing FastAPI endpoints.",
        confidence_score=0.95,
    )
    mem1 = ProvenanceQualifiedMemory(
        memory_id="mem_001",
        statement="Use pytest-asyncio for FastAPI testing",
        category="testing_convention",
        provenance=meta1,
    )
    store.save_memory(mem1)

    meta2 = ProvenanceMetadata(
        session_id="sess_alpha_101",
        message_id="msg_002",
        turn_index=4,
        quote_snippet="Never commit .env files to repository.",
        confidence_score=1.0,
    )
    mem2 = ProvenanceQualifiedMemory(
        memory_id="mem_002",
        statement="Prohibit committing .env files",
        category="security_policy",
        provenance=meta2,
    )
    store.save_memory(mem2)

    # 2. Lookup by memory ID
    retrieved = store.get_memory("mem_001")
    assert retrieved is not None
    assert retrieved.statement == "Use pytest-asyncio for FastAPI testing"
    assert retrieved.provenance.session_id == "sess_alpha_101"

    # 3. Bidirectional lookup by session_id
    session_memories = store.find_by_session("sess_alpha_101")
    assert len(session_memories) == 2
    assert session_memories[0].memory_id == "mem_001"
    assert session_memories[1].memory_id == "mem_002"

    # 4. Lookup by specific message_id
    msg_memories = store.find_by_message("msg_002")
    assert len(msg_memories) == 1
    assert msg_memories[0].memory_id == "mem_002"


def test_atomic_revocable_forget_and_zombie_resurfacing_prevention(tmp_path: Path) -> None:
    """Verifies targeted memory revocation, raw transcript protection, and anti-resurrection exclusion."""
    store = ProvenanceMemoryStore(storage_dir=tmp_path / "memory_store")
    engine = RevocableForgetEngine(store=store, tombstone_dir=tmp_path / "tombstones")

    meta = ProvenanceMetadata(
        session_id="sess_beta_202",
        message_id="msg_turn_5",
        turn_index=5,
        quote_snippet="I dislike writing docstrings for internal helper functions.",
        confidence_score=0.8,
    )
    mem = ProvenanceQualifiedMemory(
        memory_id="mem_bad_preference",
        statement="Skip docstrings on internal functions",
        category="coding_style",
        provenance=meta,
    )
    store.save_memory(mem)

    # Pre-check exclusion
    assert engine.is_excluded(
        session_id="sess_beta_202",
        message_id="msg_turn_5",
        statement="Skip docstrings on internal functions",
    ) is False

    # 1. Execute atomic forget
    result = engine.forget(
        memory_id="mem_bad_preference",
        reason="User corrected: docstrings are mandatory per team policy.",
    )
    assert result.revoked is True
    assert result.transcript_intact is True
    assert result.source_session_id == "sess_beta_202"

    # 2. Store should now filter it out from default active list
    active_mems = store.list_memories(include_revoked=False)
    assert len(active_mems) == 0

    all_mems = store.list_memories(include_revoked=True)
    assert len(all_mems) == 1
    assert all_mems[0].is_revoked is True
    assert "mandatory" in all_mems[0].revocation_reason

    # 3. Zombie resurfacing protection: fingerprint is now permanently excluded
    assert engine.is_excluded(
        session_id="sess_beta_202",
        message_id="msg_turn_5",
        statement="Skip docstrings on internal functions",
    ) is True

    # 4. Idempotent forget call
    second_result = engine.forget("mem_bad_preference")
    assert second_result.revoked is True
    assert "already revoked" in second_result.message


def test_dream_diary_recorder_lifecycle_and_query(tmp_path: Path) -> None:
    """Verifies transparent recording of background dreaming memory consolidation cycles."""
    recorder = DreamDiaryRecorder(diary_dir=tmp_path / "dream_diaries")

    # 1. Record dreaming consolidation cycle 1
    d1 = recorder.record_dream(
        agent_id="code_reviewer_bot",
        scanned_turns=35,
        promoted_memory_ids=["mem_001", "mem_002"],
        pruned_duplicates_count=4,
        duration_ms=125.5,
        status="completed",
        notes="Consolidated testing preferences from PR review discussions.",
    )
    assert d1.dream_id.startswith("dream_")
    assert d1.scanned_turns == 35
    assert len(d1.promoted_memory_ids) == 2

    # 2. Record dreaming cycle 2 for different agent
    recorder.record_dream(
        agent_id="finance_bot",
        scanned_turns=12,
        promoted_memory_ids=["mem_fin_10"],
        pruned_duplicates_count=1,
        duration_ms=45.0,
        status="completed",
        notes="Consolidated expense categorization rules.",
    )

    # 3. Query all diary entries
    all_diaries = recorder.list_entries()
    assert len(all_diaries) == 2

    # 4. Query filtered by agent_id
    code_diaries = recorder.list_entries(agent_id="code_reviewer_bot")
    assert len(code_diaries) == 1
    assert code_diaries[0].agent_id == "code_reviewer_bot"
    assert code_diaries[0].pruned_duplicates_count == 4
