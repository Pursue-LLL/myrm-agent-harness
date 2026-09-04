"""Unit and integration tests for anti-drift distillation guards and self-exclusion."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from myrm_agent_harness.toolkits.memory.strategies.distillation_guards import (
    DistillationCandidate,
    DistillationGuardRejectionError,
    DistillationOrigin,
    DistillationRejectionCode,
    EvidenceReference,
    SelfIdentityState,
    assert_distillable,
    assert_has_evidence,
    check_distillable,
    filter_distillable_messages,
    filter_memories_with_evidence,
    is_alert_or_bot_sender,
)
from myrm_agent_harness.toolkits.memory.strategies.extractor import (
    ExtractedMemory,
    extract_memories_from_conversation,
)
from myrm_agent_harness.toolkits.memory.types import (
    MemoryType,
    SemanticMemory,
)


class TestDistillationGuards:
    """Tests for core distillation guards: self-exclusion, tri-state identity, bot filtering, and evidence."""

    def test_agent_origin_permanently_excluded(self) -> None:
        """Agent self-generated messages must be permanently rejected to prevent persona drift."""
        candidate = DistillationCandidate(
            content="I suggest we always use Python 3.13 and strict typing across all modules.",
            origin=DistillationOrigin.AGENT,
            is_self=SelfIdentityState.SELF,  # Even if mislabeled as self, origin=AGENT takes hard precedence
        )
        res = check_distillable(candidate)
        assert not res.allowed
        assert res.rejection_code == DistillationRejectionCode.REJECT_ORIGIN_AGENT
        assert "Agent self-generated messages are permanently excluded" in res.rejection_reason

        with pytest.raises(DistillationGuardRejectionError) as exc_info:
            assert_distillable(candidate)
        assert exc_info.value.code == DistillationRejectionCode.REJECT_ORIGIN_AGENT

    def test_tri_state_identity_unconfirmed_rejected(self) -> None:
        """Unconfirmed identity must be strictly rejected without guessing."""
        candidate = DistillationCandidate(
            content="I prefer dark mode in all my IDE themes.",
            origin=DistillationOrigin.USER,
            is_self=SelfIdentityState.UNCONFIRMED,
        )
        res = check_distillable(candidate)
        assert not res.allowed
        assert res.rejection_code == DistillationRejectionCode.REJECT_IDENTITY_UNCONFIRMED
        assert "Speaker identity is unconfirmed" in res.rejection_reason

    def test_tri_state_identity_other_rejected(self) -> None:
        """Third-party statements are rejected from direct profile distillation."""
        candidate = DistillationCandidate(
            content="Bob prefers vim keybindings over vscode.",
            origin=DistillationOrigin.USER,
            is_self=SelfIdentityState.OTHER,
        )
        res = check_distillable(candidate)
        assert not res.allowed
        assert res.rejection_code == DistillationRejectionCode.REJECT_IDENTITY_OTHER
        assert "Third-party messages cannot be distilled" in res.rejection_reason

    def test_tri_state_identity_from_bool_or_none(self) -> None:
        """Test conversion from raw bool/None to SelfIdentityState."""
        assert SelfIdentityState.from_bool_or_none(True) == SelfIdentityState.SELF
        assert SelfIdentityState.from_bool_or_none(False) == SelfIdentityState.OTHER
        assert SelfIdentityState.from_bool_or_none(None) == SelfIdentityState.UNCONFIRMED

    def test_bot_and_monitoring_alert_excluded(self) -> None:
        """Automated monitoring bots and alert senders must be blocked from memory distillation."""
        bot_candidates = [
            DistillationCandidate(
                content="Alert: Prometheus target down in us-west-2 cluster",
                origin=DistillationOrigin.BOT,
            ),
            DistillationCandidate(
                content="CI/CD Build failed on branch main #49281",
                origin=DistillationOrigin.USER,
                is_bot_or_alert=True,
            ),
            DistillationCandidate(
                content="Sentry event: NullPointerException in UserAuthHandler",
                origin=DistillationOrigin.USER,
                sender_name="SentryBot",
            ),
            DistillationCandidate(
                content="今日打卡已完成，请注意核对工时",
                origin=DistillationOrigin.USER,
                sender_name="打卡助手",
            ),
        ]
        for candidate in bot_candidates:
            res = check_distillable(candidate)
            assert not res.allowed, f"Candidate should be rejected: {candidate.content}"
            assert res.rejection_code == DistillationRejectionCode.REJECT_BOT_OR_ALERT

    def test_bot_sender_name_heuristic(self) -> None:
        """Verify regex patterns for detecting alert and monitoring bot senders."""
        assert is_alert_or_bot_sender("Grafana-Alerts")
        assert is_alert_or_bot_sender("github-actions[bot]")
        assert is_alert_or_bot_sender("运维告警机器人")
        assert not is_alert_or_bot_sender("Alice Wang")
        assert not is_alert_or_bot_sender("Bob Zhang")

    def test_empty_content_rejected(self) -> None:
        """Whitespace or empty content is immediately rejected."""
        candidate = DistillationCandidate(content="   \n\t  ")
        res = check_distillable(candidate)
        assert not res.allowed
        assert res.rejection_code == DistillationRejectionCode.REJECT_EMPTY_CONTENT

    def test_verified_user_message_admitted(self) -> None:
        """Verified primary user messages pass all admission checks cleanly."""
        candidate = DistillationCandidate(
            content="I always configure PostgreSQL with SSL mode require.",
            origin=DistillationOrigin.USER,
            is_self=SelfIdentityState.SELF,
            sender_name="Alice",
            evidence=[
                EvidenceReference(
                    source_id="chat_123",
                    message_id="msg_456",
                    quote_snippet="I always configure PostgreSQL with SSL mode require.",
                )
            ],
        )
        res = check_distillable(candidate)
        assert res.allowed
        assert res.rejection_code is None
        # Should not raise
        assert_distillable(candidate)

    def test_filter_distillable_messages(self) -> None:
        """Conversation message filter should exclude assistant and unconfirmed messages."""
        messages = [
            {"role": "user", "content": "Hello, how do I setup Tailwind?", "id": "m1"},
            {"role": "assistant", "content": "You can run bun add -d tailwindcss", "id": "m2"},
            {"role": "user", "content": "Prometheus CPU spike 98%", "name": "AlertBot", "id": "m3"},
            {"role": "user", "content": "Unverified message from someone", "is_self": None, "id": "m4"},
            {"role": "user", "content": "I like dark mode themes", "id": "m5"},
        ]
        admitted, rejections = filter_distillable_messages(messages, default_source_id="chat_test")
        assert len(admitted) == 2
        assert admitted[0]["content"] == "Hello, how do I setup Tailwind?"
        assert admitted[1]["content"] == "I like dark mode themes"
        assert len(rejections) == 3

    def test_filter_distillable_messages_third_party_context(self) -> None:
        """Third party messages can be preserved as dialogue context when explicitly allowed."""
        messages = [
            {"role": "user", "content": "Alice: I updated the schema", "is_self": False, "id": "m1"},
            {"role": "user", "content": "Me: Thanks Alice, I will run migrations", "is_self": True, "id": "m2"},
        ]
        admitted, rejections = filter_distillable_messages(messages, allow_other_as_context=True)
        assert len(admitted) == 2
        assert admitted[0].get("_third_party_context") is True
        assert admitted[1].get("_third_party_context") is None
        assert len(rejections) == 0

    def test_evidence_provenance_assertions(self) -> None:
        """assert_has_evidence enforces that all memory facts carry concrete provenance."""
        grounded_mem = SemanticMemory(
            content="User prefers Python 3.13",
            source_chat_id="chat_abc",
            source_message_id="msg_123",
        )
        assert_has_evidence([grounded_mem])

        ungrounded_mem = SemanticMemory(
            content="Fabricated fact without source",
            source_chat_id=None,
            source_message_id=None,
        )
        with pytest.raises(ValueError) as exc_info:
            assert_has_evidence([ungrounded_mem])
        assert DistillationRejectionCode.REJECT_MISSING_EVIDENCE.value in str(exc_info.value)

    def test_filter_memories_with_evidence(self) -> None:
        """Partitioning memories by evidence anchor presence."""
        mem1 = ExtractedMemory(
            memory_type=MemoryType.SEMANTIC,
            content="Fact with message reference",
            confidence=0.9,
            source_message="I prefer FastAPI",
        )
        mem2 = ExtractedMemory(
            memory_type=MemoryType.SEMANTIC,
            content="Fact with structured evidence",
            confidence=0.9,
            evidence=[EvidenceReference(source_id="chat_1", message_id="msg_1")],
        )
        mem3 = ExtractedMemory(
            memory_type=MemoryType.SEMANTIC,
            content="Hallucinated fact with zero evidence",
            confidence=0.5,
        )

        grounded, ungrounded = filter_memories_with_evidence([mem1, mem2, mem3])
        assert len(grounded) == 2
        assert len(ungrounded) == 1
        assert ungrounded[0].content == "Hallucinated fact with zero evidence"

    def test_empty_shell_evidence_rejected(self) -> None:
        """Dangling shell evidence without message_id, quote, or channel_id must be rejected."""
        dangling_ev = EvidenceReference(source_id="chat_test", message_id=None, quote_snippet=None, channel_id=None)
        mem = ExtractedMemory(
            memory_type=MemoryType.SEMANTIC,
            content="Dangling shell test",
            confidence=0.9,
            evidence=[dangling_ev],
        )
        with pytest.raises(ValueError) as exc_info:
            assert_has_evidence([mem])
        assert DistillationRejectionCode.REJECT_MISSING_EVIDENCE.value in str(exc_info.value)

    def test_agent_as_evidence_author_rejected(self) -> None:
        """Evidentiary Trojan Horse: evidence citing Agent or Assistant as author must be blocked."""
        agent_ev = EvidenceReference(
            source_id="chat_test",
            message_id="msg_ai_1",
            author_id="Assistant",
            quote_snippet="You should definitely use strict typing",
        )
        mem = ExtractedMemory(
            memory_type=MemoryType.SEMANTIC,
            content="User prefers strict typing",
            confidence=0.9,
            evidence=[agent_ev],
        )
        with pytest.raises(ValueError) as exc_info:
            assert_has_evidence([mem])
        assert DistillationRejectionCode.REJECT_EVIDENCE_FROM_AGENT.value in str(exc_info.value)

    def test_hallucinated_quote_snippet_rejected(self) -> None:
        """Fabricated quotes not present in the user conversation corpus must be rejected."""
        hallucinated_ev = EvidenceReference(
            source_id="chat_test",
            message_id="msg_user_1",
            author_id="User",
            quote_snippet="I love eating pineapples on pizza every morning",
        )
        mem = ExtractedMemory(
            memory_type=MemoryType.SEMANTIC,
            content="User likes pineapple pizza",
            confidence=0.9,
            evidence=[hallucinated_ev],
        )
        corpus = [
            "Hello, please help me configure a PostgreSQL database on AWS RDS.",
            "Make sure SSL mode is require.",
        ]
        with pytest.raises(ValueError) as exc_info:
            assert_has_evidence([mem], allowed_verbatim_corpus=corpus)
        assert DistillationRejectionCode.REJECT_FABRICATED_QUOTE.value in str(exc_info.value)

    def test_verbatim_quote_snippet_accepted(self) -> None:
        """Verbatim quotes present in the verified corpus are accepted cleanly."""
        grounded_ev = EvidenceReference(
            source_id="chat_test",
            message_id="msg_user_1",
            author_id="User",
            quote_snippet="Make sure SSL mode is require",
        )
        mem = ExtractedMemory(
            memory_type=MemoryType.SEMANTIC,
            content="User requires SSL on databases",
            confidence=0.9,
            evidence=[grounded_ev],
        )
        corpus = [
            "Hello, please help me configure a PostgreSQL database on AWS RDS.",
            "Make sure SSL mode is require.",
        ]
        # Should not raise
        assert_has_evidence([mem], allowed_verbatim_corpus=corpus)


@pytest.mark.asyncio
class TestDistillationGuardsAsyncIntegration:
    """Integration tests verifying guards inside extraction pipeline."""

    async def test_extract_memories_guard_integration(self) -> None:
        """extract_memories_from_conversation drops unconfirmed messages and attaches evidence."""
        messages = [
            {"role": "user", "content": "never use sudo for package installs", "id": "msg_edict_1"},
            {"role": "user", "content": "Alert: Database latency high", "name": "AlertBot", "id": "msg_bot_1"},
        ]

        async def dummy_llm(system_prompt: str, user_prompt: str) -> str:
            return "[]"

        res = await extract_memories_from_conversation(messages, llm_func=dummy_llm)
        assert len(res.memories) == 2
        for procedural in res.memories:
            assert procedural.memory_type == MemoryType.PROCEDURAL
            assert "sudo" in procedural.content
            assert len(procedural.evidence) == 1
            assert procedural.evidence[0].message_id == "msg_edict_1"

    async def test_memory_extractor_direct_extract_guard(self) -> None:
        """MemoryExtractor.extract directly drops assistant and bot turns before invoking LLM."""
        from myrm_agent_harness.toolkits.memory.strategies.extractor import MemoryExtractor

        called = False

        async def inspecting_llm(system_prompt: str, user_prompt: str) -> str:
            nonlocal called
            called = True
            assert "Jenkins" not in user_prompt
            assert "Rust" not in user_prompt
            assert "PostgreSQL" in user_prompt
            return "[]"

        extractor = MemoryExtractor(llm_func=inspecting_llm)
        messages = [
            {"role": "assistant", "content": "I recommend Rust for maximum speed."},
            {"role": "user", "name": "Jenkins-CI", "content": "Build #42 passed successfully."},
            {"role": "user", "content": "I prefer PostgreSQL over MySQL for transactional storage."},
        ]

        res = await extractor.extract(messages)
        assert called is True
        assert len(res.memories) == 0

    async def test_extract_memories_all_rejected_returns_empty(self) -> None:
        """When all input messages are rejected by distillation guards, returns empty result cleanly."""
        messages = [
            {"role": "assistant", "content": "I am an AI assistant and I think we should rewrite in Rust."},
            {"role": "user", "content": "CI build failed", "name": "JenkinsBot"},
        ]

        async def dummy_llm(system_prompt: str, user_prompt: str) -> str:
            return "[]"

        res = await extract_memories_from_conversation(messages, llm_func=dummy_llm)
        assert len(res.memories) == 0

    async def test_multi_turn_mixed_conversation_drift_defense(self) -> None:
        """Full multi-turn flow: Assistant advice is excluded from extraction; fabricated quotes rejected."""
        messages = [
            {"role": "user", "content": "I prefer blue gradient buttons in my frontend.", "id": "u1"},
            {"role": "assistant", "content": "I suggest you also add heavy box-shadow and blur effects.", "id": "a1"},
            {"role": "user", "content": "No shadows please. My project strictly runs on Bun and Node 22.", "id": "u2"},
        ]

        # Simulate LLM returning two facts:
        # 1. Authentic fact grounded in user's prompt
        # 2. Hallucinated / drift fact trying to claim assistant's advice as user preference
        simulated_llm_response = (
            '[\n'
            '  {"memory_type": "semantic", "content": "User prefers blue gradient buttons", "confidence": 0.95, "importance": 0.8},\n'
            '  {"memory_type": "semantic", "content": "User prefers heavy box-shadow", "confidence": 0.9, "importance": 0.7}\n'
            ']'
        )

        async def fake_llm(system_prompt: str, user_prompt: str) -> str:
            return simulated_llm_response

        res = await extract_memories_from_conversation(messages, llm_func=fake_llm)
        # Verify memories were returned and carry evidence
        assert len(res.memories) > 0
        for mem in res.memories:
            assert len(mem.evidence) > 0
            # Evidence source must never be assistant
            assert mem.evidence[0].author_id != "assistant"


    async def test_extract_memories_filters_hallucinated_evidence_memories(self) -> None:
        """extract_memories_from_conversation drops memories whose evidence quotes are fabricated."""
        messages = [
            {"role": "user", "content": "I like dark mode themes.", "id": "m1"},
        ]

        async def hallucinating_llm(system_prompt: str, user_prompt: str) -> str:
            # LLM synthesizes a fact but fabricates a quote snippet that user never said
            return """[
                {
                    "memory_type": "semantic",
                    "content": "User likes skydiving",
                    "confidence": 0.9,
                    "importance": 0.8,
                    "evidence": [
                        {
                            "source_id": "conv_1",
                            "message_id": "m1",
                            "quote_snippet": "I regularly jump out of airplanes on weekends"
                        }
                    ]
                }
            ]"""

        res = await extract_memories_from_conversation(messages, llm_func=hallucinating_llm)
        # Fabricated quote should be filtered out by filter_memories_with_evidence
        assert len(res.memories) == 0

