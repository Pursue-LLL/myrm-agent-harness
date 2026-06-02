"""Tests for memory_extraction module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from myrm_agent_harness.agent._internals.memory_extraction import (
    _apply_deep_pii_scan,
    _get_user_real_name,
    auto_extract_memories,
    build_extraction_messages,
    create_extraction_llm_func,
    persist_extracted_memories,
)


class TestBuildExtractionMessages:
    def test_basic_conversation(self) -> None:
        messages = build_extraction_messages(
            query="What is Python?",
            chat_history=None,
            assistant_reply="Python is a language.",
        )
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "What is Python?"
        assert messages[1]["role"] == "assistant"
        assert messages[1]["content"] == "Python is a language."

    def test_multimodal_query(self) -> None:
        messages = build_extraction_messages(
            query=[{"type": "image", "url": "x.png"}],
            chat_history=None,
            assistant_reply="I see an image.",
        )
        assert messages[0]["content"] == "[multimodal]"

    def test_empty_reply_omitted(self) -> None:
        messages = build_extraction_messages(
            query="hello", chat_history=None, assistant_reply=""
        )
        assert len(messages) == 1

    @patch("myrm_agent_harness.utils.chat_utils.convert_chat_history_simple")
    def test_with_chat_history(self, mock_convert: MagicMock) -> None:
        mock_convert.return_value = [
            HumanMessage(content="prev q"),
            AIMessage(content="prev a"),
        ]
        messages = build_extraction_messages(
            query="new q",
            chat_history=[{"role": "user", "content": "prev q"}],
            assistant_reply="new a",
        )
        assert len(messages) == 4
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert messages[2]["role"] == "user"
        assert messages[3]["role"] == "assistant"


class TestCreateExtractionLlmFunc:
    @pytest.mark.asyncio
    async def test_calls_llm_with_messages(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content="extracted memories")

        func = create_extraction_llm_func(mock_llm)
        result = await func("system prompt", "user prompt")
        assert result == "extracted memories"
        mock_llm.ainvoke.assert_called_once()
        call_args = mock_llm.ainvoke.call_args[0][0]
        assert len(call_args) == 2

    @pytest.mark.asyncio
    async def test_no_system_prompt(self) -> None:
        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content="result")

        func = create_extraction_llm_func(mock_llm)
        await func("", "user prompt")
        call_args = mock_llm.ainvoke.call_args[0][0]
        assert len(call_args) == 1


class TestAutoExtractMemories:
    @pytest.mark.asyncio
    async def test_skips_empty_reply(self) -> None:
        mock_manager = MagicMock()
        mock_llm = AsyncMock()
        await auto_extract_memories(
            query="hello",
            chat_history=None,
            memory_manager=mock_manager,
            llm=mock_llm,
            assistant_reply="",
        )
        mock_llm.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_trivial_conversation(self) -> None:
        mock_manager = MagicMock()
        mock_llm = AsyncMock()
        await auto_extract_memories(
            query="hi",
            chat_history=None,
            memory_manager=mock_manager,
            llm=mock_llm,
            assistant_reply="hello",
        )
        mock_llm.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_extracts_and_persists(self) -> None:
        mock_memory = MagicMock()
        mock_memory.importance = "high"

        mock_result = MagicMock()
        mock_result.memories = [mock_memory]
        mock_result.extraction_time_ms = 100.0

        mock_extractor = MagicMock()
        mock_extractor.extract = AsyncMock(return_value=mock_result)

        mock_manager = MagicMock()
        mock_manager.user_id = "user1"
        mock_manager.store_batch = AsyncMock(return_value=[])

        mock_llm = AsyncMock()
        mock_llm.ainvoke.return_value = MagicMock(content="extraction result")

        with (
            patch(
                "myrm_agent_harness.toolkits.memory.strategies.extractor.MemoryExtractor",
                return_value=mock_extractor,
            ),
            patch(
                "myrm_agent_harness.toolkits.memory.strategies.extractor.ExtractionConfig"
            ),
            patch(
                "myrm_agent_harness.agent._internals.memory_extraction.persist_extracted_memories",
                new_callable=AsyncMock,
                return_value=1,
            ),
        ):
            await auto_extract_memories(
                query="Tell me about Python's history and its design philosophy in detail",
                chat_history=None,
                memory_manager=mock_manager,
                llm=mock_llm,
                assistant_reply="A" * 200,
            )

        mock_extractor.extract.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_extraction_error_gracefully(self) -> None:
        mock_manager = MagicMock()
        mock_manager.user_id = "user1"
        mock_llm = AsyncMock()
        mock_llm.ainvoke.side_effect = RuntimeError("LLM failed")

        await auto_extract_memories(
            query="Tell me about Python",
            chat_history=None,
            memory_manager=mock_manager,
            llm=mock_llm,
            assistant_reply="A" * 200,
        )


class TestPersistExtractedMemories:
    @pytest.mark.asyncio
    async def test_empty_memories(self) -> None:
        mock_manager = MagicMock()
        mock_manager.store_batch = AsyncMock(return_value=[])

        with patch(
            "myrm_agent_harness.toolkits.memory.strategies.extractor.MemoryExtractor"
        ) as mock_cls:
            mock_extractor = MagicMock()
            mock_extractor.to_concrete_memories.return_value = []
            mock_cls.return_value = mock_extractor

            count = await persist_extracted_memories([], mock_manager, "chat1")
            assert count == 0

    @pytest.mark.asyncio
    async def test_deep_scan_llm_func_applies_pseudonymization(self) -> None:
        """Verify deep_scan_llm_func triggers LLM-based PII detection on memories."""
        import json
        import tempfile
        from pathlib import Path

        from myrm_agent_harness.agent.security.detection.pseudonym_store import PseudonymStore

        mock_memory = MagicMock()
        mock_memory.content = "User has penicillin allergy"
        mock_memory.importance = "high"

        mock_manager = MagicMock()
        mock_manager.store_batch = AsyncMock(return_value=[mock_memory])
        mock_manager.get_profile_attribute = AsyncMock(return_value=None)

        tmp = tempfile.mkdtemp()
        store = PseudonymStore(str(Path(tmp) / "test.db"))

        async def _mock_llm(_s: str, _u: str) -> str:
            return json.dumps([[
                {"original_text": "penicillin allergy", "privacy_type": "Medical Health", "privacy_level": "PL3"}
            ]])

        with (
            patch(
                "myrm_agent_harness.toolkits.memory.strategies.extractor.MemoryExtractor"
            ) as mock_cls,
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_pseudonym_store",
                return_value=store,
            ),
        ):
            mock_extractor = MagicMock()
            mock_extractor.to_concrete_memories.return_value = [mock_memory]
            mock_cls.return_value = mock_extractor

            count = await persist_extracted_memories(
                [MagicMock()], mock_manager, "chat1",
                deep_scan_llm_func=_mock_llm,
            )
            assert count >= 0
            assert "penicillin allergy" not in mock_memory.content
            assert "<MEDICAL_HEALTH_1>" in mock_memory.content

        store.close()

    @pytest.mark.asyncio
    async def test_deep_scan_none_skips_llm_detection(self) -> None:
        """Verify no LLM call when deep_scan_llm_func is None."""
        mock_memory = MagicMock()
        mock_memory.content = "User has diabetes"

        mock_manager = MagicMock()
        mock_manager.store_batch = AsyncMock(return_value=[mock_memory])

        with patch(
            "myrm_agent_harness.toolkits.memory.strategies.extractor.MemoryExtractor"
        ) as mock_cls:
            mock_extractor = MagicMock()
            mock_extractor.to_concrete_memories.return_value = [mock_memory]
            mock_cls.return_value = mock_extractor

            await persist_extracted_memories(
                [MagicMock()], mock_manager, "chat1",
                deep_scan_llm_func=None,
            )
            assert mock_memory.content == "User has diabetes"


class TestApplyDeepPIIScan:
    """Tests for _apply_deep_pii_scan helper."""

    @pytest.mark.asyncio
    async def test_store_none_returns_original(self) -> None:
        """When PseudonymStore is not initialized, memories pass through unchanged."""
        mock_memory = MagicMock()
        mock_memory.content = "User has severe anxiety disorder"

        mock_manager = MagicMock()
        mock_manager.get_profile_attribute = AsyncMock(return_value=None)

        async def _mock_llm(_s: str, _u: str) -> str:
            raise AssertionError("LLM should not be called when store is None")

        with patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_pseudonym_store",
            return_value=None,
        ):
            result = await _apply_deep_pii_scan([mock_memory], _mock_llm, mock_manager)
            assert result[0].content == "User has severe anxiety disorder"

    @pytest.mark.asyncio
    async def test_llm_failure_keeps_original(self) -> None:
        """When LLM call raises exception, memories pass through (fail-open)."""
        import tempfile
        from pathlib import Path

        from myrm_agent_harness.agent.security.detection.pseudonym_store import PseudonymStore

        mock_memory = MagicMock()
        mock_memory.content = "User has diabetes and asthma"

        mock_manager = MagicMock()
        mock_manager.get_profile_attribute = AsyncMock(return_value=None)

        tmp = tempfile.mkdtemp()
        store = PseudonymStore(str(Path(tmp) / "test.db"))

        async def _fail_llm(_s: str, _u: str) -> str:
            raise RuntimeError("LLM unavailable")

        with patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_pseudonym_store",
            return_value=store,
        ):
            result = await _apply_deep_pii_scan([mock_memory], _fail_llm, mock_manager)
            assert result[0].content == "User has diabetes and asthma"

        store.close()

    @pytest.mark.asyncio
    async def test_no_pii_detected_keeps_original(self) -> None:
        """When LLM finds no PII, content stays unchanged."""
        import json
        import tempfile
        from pathlib import Path

        from myrm_agent_harness.agent.security.detection.pseudonym_store import PseudonymStore

        mock_memory = MagicMock()
        mock_memory.content = "The weather is nice today"

        mock_manager = MagicMock()
        mock_manager.get_profile_attribute = AsyncMock(return_value=None)

        tmp = tempfile.mkdtemp()
        store = PseudonymStore(str(Path(tmp) / "test.db"))

        async def _mock_llm(_s: str, _u: str) -> str:
            return json.dumps([[]])

        with patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_pseudonym_store",
            return_value=store,
        ):
            result = await _apply_deep_pii_scan([mock_memory], _mock_llm, mock_manager)
            assert result[0].content == "The weather is nice today"

        store.close()

    @pytest.mark.asyncio
    async def test_multiple_memories_batch(self) -> None:
        """Multiple memories are batch-processed in a single LLM call."""
        import json
        import tempfile
        from pathlib import Path

        from myrm_agent_harness.agent.security.detection.pseudonym_store import PseudonymStore

        mem1 = MagicMock()
        mem1.content = "User has asthma"
        mem2 = MagicMock()
        mem2.content = "Clean text without PII"
        mem3 = MagicMock()
        mem3.content = "User is Buddhist"

        mock_manager = MagicMock()
        mock_manager.get_profile_attribute = AsyncMock(return_value=None)

        tmp = tempfile.mkdtemp()
        store = PseudonymStore(str(Path(tmp) / "test.db"))

        call_count = 0

        async def _mock_llm(_s: str, _u: str) -> str:
            nonlocal call_count
            call_count += 1
            return json.dumps([
                [{"original_text": "asthma", "privacy_type": "Medical Health", "privacy_level": "PL3"}],
                [],
                [{"original_text": "Buddhist", "privacy_type": "Sensitive Identity", "privacy_level": "PL3"}],
            ])

        with patch(
            "myrm_agent_harness.agent.middlewares._session_context.get_pseudonym_store",
            return_value=store,
        ):
            result = await _apply_deep_pii_scan([mem1, mem2, mem3], _mock_llm, mock_manager)
            assert call_count == 1
            assert "asthma" not in result[0].content
            assert result[1].content == "Clean text without PII"
            assert "Buddhist" not in result[2].content

        store.close()


class TestGetUserRealName:
    """Tests for _get_user_real_name helper."""

    @pytest.mark.asyncio
    async def test_returns_name_from_profile(self) -> None:
        mock_manager = MagicMock()
        mock_manager.get_profile_attribute = AsyncMock(side_effect=lambda k: "张三" if k == "name" else None)
        name = await _get_user_real_name(mock_manager)
        assert name == "张三"

    @pytest.mark.asyncio
    async def test_returns_real_name_fallback(self) -> None:
        mock_manager = MagicMock()
        mock_manager.get_profile_attribute = AsyncMock(side_effect=lambda k: "John" if k == "real_name" else None)
        name = await _get_user_real_name(mock_manager)
        assert name == "John"

    @pytest.mark.asyncio
    async def test_returns_empty_on_no_profile(self) -> None:
        mock_manager = MagicMock()
        mock_manager.get_profile_attribute = AsyncMock(return_value=None)
        name = await _get_user_real_name(mock_manager)
        assert name == ""

    @pytest.mark.asyncio
    async def test_returns_empty_on_exception(self) -> None:
        mock_manager = MagicMock()
        mock_manager.get_profile_attribute = AsyncMock(side_effect=RuntimeError("DB down"))
        name = await _get_user_real_name(mock_manager)
        assert name == ""


class TestDefaultEnabledBehavior:
    """Test default enable_memory_auto_extraction=True behavior."""

    def test_skill_agent_default_value_is_true(self) -> None:
        """Verify SkillAgent has enable_memory_auto_extraction=True by default."""
        import inspect

        from myrm_agent_harness.agent.skill_agent import SkillAgent

        sig = inspect.signature(SkillAgent.__init__)
        param = sig.parameters["enable_memory_auto_extraction"]
        assert (
            param.default is True
        ), "enable_memory_auto_extraction should default to True"

    def test_skill_agent_factory_default_value_is_true(self) -> None:
        """Verify create_skill_agent has enable_memory_auto_extraction=True by default."""
        import inspect

        from myrm_agent_harness.agent.skill_agent_factory import create_skill_agent

        sig = inspect.signature(create_skill_agent)
        param = sig.parameters["enable_memory_auto_extraction"]
        assert param.default is True, "create_skill_agent should default to True"

    def test_agent_accepts_enable_parameter(self) -> None:
        """Test that SkillAgent correctly accepts and stores enable_memory_auto_extraction parameter."""
        from unittest.mock import MagicMock

        from myrm_agent_harness.agent.skill_agent import SkillAgent

        mock_llm = MagicMock()

        # Test with True
        agent_enabled = SkillAgent(llm=mock_llm, enable_memory_auto_extraction=True)
        assert agent_enabled._enable_memory_auto_extraction is True

        # Test with False
        agent_disabled = SkillAgent(llm=mock_llm, enable_memory_auto_extraction=False)
        assert agent_disabled._enable_memory_auto_extraction is False

        # Test default (should be True)
        agent_default = SkillAgent(llm=mock_llm)
        assert agent_default._enable_memory_auto_extraction is True
