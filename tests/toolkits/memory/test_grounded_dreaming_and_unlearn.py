"""Unit tests for Grounded Dreaming and Surgical Session Memory Unlearning.

Validates idle-time cross-session fact consolidation, dream diary serialization,
and precision unlearning of session-derived memories without damaging chat histories.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.memory import (
    DreamDiaryEntry,
    DreamDiaryStatus,
    DreamSessionFragment,
    GroundedDreamingEngine,
    SurgicalSessionMemoryUnlearner,
    SurgicalUnlearnReport,
)


class TestGroundedDreamingEngine:
    """Test suite for GroundedDreamingEngine cross-session consolidation."""

    def test_single_session_fragment_distillation(self) -> None:
        engine = GroundedDreamingEngine()
        fragment = DreamSessionFragment(
            session_id="session_001",
            memories=[
                {
                    "content": "User prefers dark mode in UI interfaces",
                    "confidence": 0.8,
                    "evidence": [{"quote_snippet": "Please switch to dark theme"}],
                }
            ],
            chat_turn_count=4,
        )

        entries = engine.process_fragments([fragment])
        assert len(entries) == 1
        entry = entries[0]
        assert "dark mode" in entry.cognitive_statement
        assert entry.source_session_ids == ["session_001"]
        assert "Please switch to dark theme" in entry.evidence_snippets
        assert entry.confidence_delta == 0.1
        assert entry.status == DreamDiaryStatus.PENDING

    def test_cross_session_consensus_reinforcement(self) -> None:
        engine = GroundedDreamingEngine()
        # Two distinct sessions mention Python 3.12 and uv
        fragment_a = DreamSessionFragment(
            session_id="sess_alpha",
            memories=[
                {
                    "content": "User builds backend services with Python 3.12 and uv package manager",
                    "confidence": 0.7,
                    "evidence": [{"quote_snippet": "Always use uv run with python 3.12"}],
                }
            ],
        )
        fragment_b = DreamSessionFragment(
            session_id="sess_beta",
            memories=[
                {
                    "content": "User prefers python 3.12 and uv for fast builds",
                    "confidence": 0.85,
                    "evidence": [{"quote_snippet": "Ensure uv is used across repos"}],
                }
            ],
        )

        entries = engine.process_fragments([fragment_a, fragment_b])
        assert len(entries) == 1
        entry = entries[0]
        # Cross-session cluster recognized
        assert "[Cross-Session Validated]" in entry.cognitive_statement
        assert set(entry.source_session_ids) == {"sess_alpha", "sess_beta"}
        assert len(entry.evidence_snippets) >= 2
        assert entry.confidence_delta >= 0.2

    def test_empty_or_blank_fragments(self) -> None:
        engine = GroundedDreamingEngine()
        assert engine.process_fragments([]) == []

        empty_frag = DreamSessionFragment(session_id="sess_empty", memories=[])
        assert engine.process_fragments([empty_frag]) == []

    def test_dream_diary_serialization_roundtrip(self) -> None:
        entry = DreamDiaryEntry.create(
            cognitive_statement="Prefers Kubernetes deployments with Helm charts",
            source_session_ids=["sess_k8s_1", "sess_k8s_2"],
            evidence_snippets=["Deploy on k8s cluster", "Use helm chart templates"],
            confidence_delta=0.25,
        )
        data = entry.to_dict()
        assert data["entry_id"] == entry.entry_id
        assert data["cognitive_statement"] == entry.cognitive_statement
        assert data["confidence_delta"] == 0.25
        assert data["status"] == "pending"

        restored = DreamDiaryEntry.from_dict(data)
        assert restored.entry_id == entry.entry_id
        assert restored.cognitive_statement == entry.cognitive_statement
        assert restored.source_session_ids == ["sess_k8s_1", "sess_k8s_2"]
        assert restored.confidence_delta == 0.25
        assert restored.status == DreamDiaryStatus.PENDING


class TestSurgicalSessionMemoryUnlearner:
    """Test suite for SurgicalSessionMemoryUnlearner precision erasure."""

    def test_match_session_derived_memories(self) -> None:
        memories: list[dict[str, object]] = [
            # 1. Direct root session_id
            {
                "id": "mem_001",
                "session_id": "target_sess",
                "content": "Fact A",
            },
            # 2. Metadata session_id
            {
                "id": "mem_002",
                "metadata": {"session_id": "target_sess"},
                "content": "Fact B",
            },
            # 3. Evidence channel_id linkage
            {
                "id": "mem_003",
                "evidence": [{"source_id": "other_id", "channel_id": "target_sess"}],
                "content": "Fact C",
            },
            # 4. Unrelated memory
            {
                "id": "mem_004",
                "session_id": "different_sess",
                "content": "Unrelated fact",
            },
        ]

        matched = SurgicalSessionMemoryUnlearner.match_session_derived_memories(
            "target_sess", memories
        )
        assert matched == ["mem_001", "mem_002", "mem_003"]

    def test_match_session_derived_memories_empty(self) -> None:
        assert (
            SurgicalSessionMemoryUnlearner.match_session_derived_memories(
                "", [{"id": "m1", "session_id": "s1"}]
            )
            == []
        )
        assert (
            SurgicalSessionMemoryUnlearner.match_session_derived_memories("s1", [])
            == []
        )

    @pytest.mark.asyncio
    async def test_unlearn_session_with_deleter(self) -> None:
        purged_ids: list[str] = []

        async def mock_deleter(ids: list[str]) -> int:
            purged_ids.extend(ids)
            return len(ids)

        memories: list[dict[str, object]] = [
            {"id": "m_target_1", "session_id": "bad_session"},
            {"id": "m_target_2", "metadata": {"session_id": "bad_session"}},
            {"id": "m_keep", "session_id": "good_session"},
        ]

        report = await SurgicalSessionMemoryUnlearner.unlearn_session(
            session_id="bad_session",
            memory_items=memories,
            deleter=mock_deleter,
            chat_turn_count=12,
        )

        assert isinstance(report, SurgicalUnlearnReport)
        assert report.session_id == "bad_session"
        assert report.unlearned_memory_ids == ["m_target_1", "m_target_2"]
        assert report.purged_vector_count == 2
        assert report.preserved_chat_turns == 12
        assert report.status == "completed"
        assert report.execution_time_ms >= 0.0
        assert purged_ids == ["m_target_1", "m_target_2"]

        # Verify serialization
        data = report.to_dict()
        assert data["session_id"] == "bad_session"
        assert data["purged_vector_count"] == 2
        assert data["preserved_chat_turns"] == 12
