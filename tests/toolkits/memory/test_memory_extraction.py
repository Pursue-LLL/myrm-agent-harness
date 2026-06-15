"""Unit tests for memory extraction via MemoryExtractor.

Tests LLM-based memory extraction, filtering, conversion, and error handling.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory.strategies.extractor import (
    ExtractionConfig,
    ExtractionMode,
    ExtractionResult,
    FeedbackSignal,
    MemoryExtractor,
    _parse_response,
    _truncate_messages_head_tail,
    detect_correction_signals,
    detect_feedback_signals,
)
from myrm_agent_harness.toolkits.memory.types import (
    ClaimConflictState,
    ClaimGraphState,
    DigestKind,
    EpisodicMemory,
    EvaporationState,
    MemoryTier,
    MemoryType,
    ProceduralMemory,
    ProfileEntry,
    SemanticMemory,
)

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def default_config() -> ExtractionConfig:
    """Create default extraction config."""
    return ExtractionConfig(
        mode=ExtractionMode.HYBRID,
        extract_profile=True,
        extract_semantic=True,
        extract_episodic=True,
        extract_procedural=True,
        min_confidence=0.7,
        min_importance=0.5,
        max_extractions_per_turn=3,
    )


@pytest.fixture
def mock_llm_func():
    """Create mock LLM function."""
    return AsyncMock()


# ============================================================================
# Correction Signal Detection Tests
# ============================================================================


class TestDetectCorrectionSignals:
    """Test detect_correction_signals pure function."""

    @pytest.mark.parametrize(
        "text",
        [
            "That's wrong, it should be X",
            "that is incorrect",
            "That is not right",
            "that's not what I asked",
            "you misunderstood me",
            "you got it wrong",
            "you made a mistake",
            "No, I meant something else",
            "no. I said this",
            "Actually, it should be Y",
            "actually, you should use Z",
            "actually, the correct answer is",
        ],
    )
    def test_english_positive(self, text: str):
        msgs = [{"role": "user", "content": text}]
        assert detect_correction_signals(msgs) is True

    @pytest.mark.parametrize(
        "text",
        [
            "不对，应该是这样",
            "你理解错了",
            "你搞错了",
            "你弄错了",
            "你理解有误",
            "重新来",
            "重新做一次",
            "重新试",
            "换一种方式",
            "不是这样的",
        ],
    )
    def test_chinese_positive(self, text: str):
        msgs = [{"role": "user", "content": text}]
        assert detect_correction_signals(msgs) is True

    def test_no_correction_signals(self):
        msgs = [
            {"role": "user", "content": "Hello, how are you?"},
            {"role": "assistant", "content": "I'm doing well!"},
            {"role": "user", "content": "Can you help me with Python?"},
        ]
        assert detect_correction_signals(msgs) is False

    def test_only_scans_user_messages(self):
        msgs = [
            {"role": "assistant", "content": "That's wrong, I apologize"},
            {"role": "user", "content": "Thanks for the correction"},
        ]
        assert detect_correction_signals(msgs) is False

    def test_empty_messages(self):
        assert detect_correction_signals([]) is False

    def test_scans_within_window(self):
        old_msgs = [
            {"role": "user", "content": f"normal message {i}"} for i in range(10)
        ]
        old_msgs[0]["content"] = "不对"
        assert detect_correction_signals(old_msgs) is False

    def test_recent_correction_detected(self):
        msgs = [{"role": "user", "content": f"normal {i}"} for i in range(4)]
        msgs.append({"role": "user", "content": "你搞错了"})
        assert detect_correction_signals(msgs) is True

    def test_skips_empty_content(self):
        msgs = [{"role": "user", "content": "  "}, {"role": "user", "content": ""}]
        assert detect_correction_signals(msgs) is False

    def test_case_insensitive_english(self):
        msgs = [{"role": "user", "content": "THAT'S WRONG"}]
        assert detect_correction_signals(msgs) is True

    @pytest.mark.parametrize(
        "text",
        [
            "错了",
            "你错了",
            "不是我要的",
            "不是我想要的效果",
            "please redo this part",
            "try again with a different approach",
            "should be Python not JavaScript",
        ],
    )
    def test_extended_patterns_positive(self, text: str):
        msgs = [{"role": "user", "content": text}]
        assert detect_correction_signals(msgs) is True

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("That's a great idea", False),
            ("Can you help me write a function?", False),
            ("I want to build a web scraper", False),
            ("Hello, how are you doing today?", False),
            ("What is the weather like?", False),
            ("The code runs correctly now", False),
            ("Thanks, that looks good", False),
            ("Let me know when you're done", False),
            ("我想写一个脚本", False),
            ("帮我查一下天气", False),
            ("代码运行正常", False),
            ("谢谢你的帮助", False),
        ],
    )
    def test_false_positive_guard(self, text: str, expected: bool):
        """Normal conversation should NOT trigger correction detection."""
        msgs = [{"role": "user", "content": text}]
        assert detect_correction_signals(msgs) is expected

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("重新开始一个项目", False),
            ("换一种颜色试试", True),
        ],
    )
    def test_boundary_cases(self, text: str, expected: bool):
        """Boundary cases: '重新开始' is not a correction signal (no '来/做/试' suffix)."""
        msgs = [{"role": "user", "content": text}]
        assert detect_correction_signals(msgs) is expected


# ============================================================================
# Feedback Signal Detection Tests
# ============================================================================


class TestDetectFeedbackSignals:
    """Test detect_feedback_signals (positive/negative/none classification)."""

    @pytest.mark.parametrize(
        "text",
        [
            "That's exactly right!",
            "Perfect, thank you!",
            "Awesome, that's what I needed",
            "You nailed it",
            "Great job!",
            "That's correct",
            "Thank you so much",
            "You remembered!",
        ],
    )
    def test_english_positive(self, text: str):
        msgs = [{"role": "user", "content": text}]
        assert detect_feedback_signals(msgs) == FeedbackSignal.POSITIVE

    @pytest.mark.parametrize(
        "text",
        [
            "太好了",
            "太棒了",
            "非常好",
            "完全正确",
            "就是这个",
            "就是我要的",
            "没错",
            "对的",
            "你记住了",
            "记得准",
        ],
    )
    def test_chinese_positive(self, text: str):
        msgs = [{"role": "user", "content": text}]
        assert detect_feedback_signals(msgs) == FeedbackSignal.POSITIVE

    @pytest.mark.parametrize(
        "text",
        [
            "That's wrong",
            "You misunderstood me",
            "不对",
            "你搞错了",
            "错了",
            "记错了",
        ],
    )
    def test_negative(self, text: str):
        msgs = [{"role": "user", "content": text}]
        assert detect_feedback_signals(msgs) == FeedbackSignal.NEGATIVE

    def test_no_feedback(self):
        msgs = [{"role": "user", "content": "What's the weather today?"}]
        assert detect_feedback_signals(msgs) == FeedbackSignal.NONE

    def test_negative_takes_priority(self):
        """When both negative and positive patterns match, negative wins."""
        msgs = [{"role": "user", "content": "That's wrong, but great job trying"}]
        assert detect_feedback_signals(msgs) == FeedbackSignal.NEGATIVE

    def test_empty_messages(self):
        assert detect_feedback_signals([]) == FeedbackSignal.NONE

    def test_only_scans_user_messages(self):
        msgs = [
            {"role": "assistant", "content": "太好了"},
            {"role": "user", "content": "Tell me more about Python"},
        ]
        assert detect_feedback_signals(msgs) == FeedbackSignal.NONE

    def test_correction_signals_backward_compat(self):
        """detect_correction_signals should still work as before."""
        pos_msgs = [{"role": "user", "content": "太好了"}]
        neg_msgs = [{"role": "user", "content": "你搞错了"}]
        none_msgs = [{"role": "user", "content": "Hello"}]
        assert detect_correction_signals(pos_msgs) is False
        assert detect_correction_signals(neg_msgs) is True
        assert detect_correction_signals(none_msgs) is False

    def test_scan_window_limit(self):
        """Positive feedback outside the scan window is ignored."""
        old_msgs = [{"role": "user", "content": f"normal {i}"} for i in range(10)]
        old_msgs[0]["content"] = "太好了"
        assert detect_feedback_signals(old_msgs) == FeedbackSignal.NONE

    def test_recent_positive_detected(self):
        msgs = [{"role": "user", "content": f"normal {i}"} for i in range(4)]
        msgs.append({"role": "user", "content": "非常好"})
        assert detect_feedback_signals(msgs) == FeedbackSignal.POSITIVE

    def test_negative_overrides_earlier_positive(self):
        """Negative in a later message overrides positive in an earlier message."""
        msgs = [
            {"role": "user", "content": "太好了"},
            {"role": "user", "content": "不对，我说错了"},
        ]
        assert detect_feedback_signals(msgs) == FeedbackSignal.NEGATIVE


# ============================================================================
# Response Parsing Tests
# ============================================================================


class TestResponseParsing:
    """Test _parse_response function."""

    def test_parse_valid_json_array(self):
        """Test parsing valid JSON array."""
        raw = """[
            {
                "memory_type": "profile",
                "content": "User name is Alice",
                "confidence": 0.95,
                "importance": 0.8,
                "profile_key": "name",
                "profile_value": "Alice"
            }
        ]"""
        memories = _parse_response(raw)
        assert len(memories) == 1
        assert memories[0].memory_type == MemoryType.PROFILE
        assert memories[0].content == "User name is Alice"
        assert memories[0].confidence == 0.95
        assert memories[0].profile_key == "name"

    def test_parse_json_with_code_fences(self):
        """Test parsing JSON wrapped in markdown code fences."""
        raw = """```json
[
    {"memory_type": "semantic", "content": "Likes Python", "confidence": 0.9, "importance": 0.7}
]
```"""
        memories = _parse_response(raw)
        assert len(memories) == 1
        assert memories[0].memory_type == MemoryType.SEMANTIC
        assert memories[0].content == "Likes Python"

    def test_parse_empty_array(self):
        """Test parsing empty array."""
        raw = "[]"
        memories = _parse_response(raw)
        assert memories == []

    def test_parse_invalid_json_returns_empty(self):
        """Test invalid JSON returns empty list."""
        raw = "invalid json {{"
        memories = _parse_response(raw)
        assert memories == []

    def test_parse_multiple_memories(self):
        """Test parsing multiple memories."""
        raw = """[
            {"memory_type": "semantic", "content": "Fact 1", "confidence": 0.9, "importance": 0.8},
            {"memory_type": "episodic", "content": "Event 1", "confidence": 0.85, "importance": 0.7},
            {"memory_type": "procedural", "content": "Rule 1", "confidence": 0.95, "importance": 0.9,
             "trigger": "when X", "action": "do Y"}
        ]"""
        memories = _parse_response(raw)
        assert len(memories) == 3
        assert memories[0].memory_type == MemoryType.SEMANTIC
        assert memories[1].memory_type == MemoryType.EPISODIC
        assert memories[2].memory_type == MemoryType.PROCEDURAL

    def test_parse_source_error_snake_case(self):
        """Test parsing source_error from LLM output (snake_case)."""
        raw = """[{
            "memory_type": "semantic",
            "content": "User prefers tabs",
            "confidence": 0.95,
            "importance": 0.8,
            "source_error": "Agent used spaces instead of tabs"
        }]"""
        memories = _parse_response(raw)
        assert len(memories) == 1
        assert memories[0].source_error == "Agent used spaces instead of tabs"

    def test_parse_source_error_camel_case(self):
        """Test parsing sourceError from LLM output (camelCase)."""
        raw = """[{
            "memory_type": "semantic",
            "content": "Correct approach is X",
            "confidence": 0.95,
            "importance": 0.8,
            "sourceError": "Agent tried approach Y which failed"
        }]"""
        memories = _parse_response(raw)
        assert len(memories) == 1
        assert memories[0].source_error == "Agent tried approach Y which failed"

    def test_parse_source_error_absent(self):
        """Test source_error is None when not provided by LLM."""
        raw = """[{
            "memory_type": "semantic",
            "content": "Normal fact",
            "confidence": 0.9,
            "importance": 0.7
        }]"""
        memories = _parse_response(raw)
        assert len(memories) == 1
        assert memories[0].source_error is None


# ============================================================================
# MemoryExtractor Tests
# ============================================================================


class TestMemoryExtractor:
    """Test MemoryExtractor class."""

    @pytest.mark.asyncio
    async def test_extract_profile_memory(self, default_config, mock_llm_func):
        """Test extracting profile memory."""
        mock_llm_func.return_value = """[
            {
                "memory_type": "profile",
                "content": "User name is Bob",
                "confidence": 0.95,
                "importance": 0.9,
                "profile_key": "name",
                "profile_value": "Bob"
            }
        ]"""

        extractor = MemoryExtractor(config=default_config, llm_func=mock_llm_func)
        messages = [
            {"role": "user", "content": "My name is Bob"},
            {"role": "assistant", "content": "Nice to meet you, Bob!"},
        ]

        result = await extractor.extract(messages)

        assert len(result.memories) == 1
        assert result.memories[0].memory_type == MemoryType.PROFILE
        assert result.memories[0].profile_key == "name"
        assert result.memories[0].profile_value == "Bob"
        assert result.extraction_time_ms > 0
        mock_llm_func.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_semantic_memory_with_preference(
        self, default_config, mock_llm_func
    ):
        """Test extracting semantic memory with preference."""
        mock_llm_func.return_value = """[
            {
                "memory_type": "semantic",
                "content": "Prefers dark mode in code editors",
                "confidence": 0.9,
                "importance": 0.7,
                "preference_type": "explicit",
                "preference_strength": 0.8
            }
        ]"""

        extractor = MemoryExtractor(config=default_config, llm_func=mock_llm_func)
        messages = [
            {"role": "user", "content": "I always use dark mode when coding"},
            {"role": "assistant", "content": "Noted!"},
        ]

        result = await extractor.extract(messages)

        assert len(result.memories) == 1
        mem = result.memories[0]
        assert mem.memory_type == MemoryType.SEMANTIC
        assert mem.preference_type == "explicit"
        assert mem.preference_strength == 0.8

    @pytest.mark.asyncio
    async def test_extract_episodic_memory(self, default_config, mock_llm_func):
        """Test extracting episodic memory."""
        mock_llm_func.return_value = """[
            {
                "memory_type": "episodic",
                "content": "Fixed authentication bug in login API on 2026-03-10",
                "confidence": 0.9,
                "importance": 0.8,
                "source_message": "I fixed the auth bug today"
            }
        ]"""

        extractor = MemoryExtractor(config=default_config, llm_func=mock_llm_func)
        messages = [
            {"role": "user", "content": "I fixed the auth bug in the login API today"},
            {"role": "assistant", "content": "Great work!"},
        ]

        result = await extractor.extract(messages)

        assert len(result.memories) == 1
        assert result.memories[0].memory_type == MemoryType.EPISODIC
        assert "2026-03-10" in result.memories[0].content

    @pytest.mark.asyncio
    async def test_extract_procedural_memory(self, default_config, mock_llm_func):
        """Test extracting procedural memory."""
        mock_llm_func.return_value = """[
            {
                "memory_type": "procedural",
                "content": "When deploying to prod, run tests first",
                "confidence": 0.95,
                "importance": 0.9,
                "trigger": "deploying to production",
                "action": "run full test suite"
            }
        ]"""

        extractor = MemoryExtractor(config=default_config, llm_func=mock_llm_func)
        messages = [
            {"role": "user", "content": "Always run tests before deploying to prod"},
            {"role": "assistant", "content": "Good practice!"},
        ]

        result = await extractor.extract(messages)

        assert len(result.memories) == 1
        mem = result.memories[0]
        assert mem.memory_type == MemoryType.PROCEDURAL
        assert mem.trigger == "deploying to production"
        assert mem.action == "run full test suite"

    @pytest.mark.asyncio
    async def test_filters_low_confidence_memories(self, default_config, mock_llm_func):
        """Test filtering out low confidence memories."""
        mock_llm_func.return_value = """[
            {"memory_type": "semantic", "content": "High conf", "confidence": 0.9, "importance": 0.8},
            {"memory_type": "semantic", "content": "Low conf", "confidence": 0.5, "importance": 0.8}
        ]"""

        extractor = MemoryExtractor(config=default_config, llm_func=mock_llm_func)
        messages = [
            {"role": "user", "content": "Test"},
            {"role": "assistant", "content": "OK"},
        ]

        result = await extractor.extract(messages)

        assert len(result.memories) == 1
        assert result.memories[0].content == "High conf"

    @pytest.mark.asyncio
    async def test_filters_low_importance_memories(self, default_config, mock_llm_func):
        """Test filtering out low importance memories."""
        mock_llm_func.return_value = """[
            {"memory_type": "semantic", "content": "High imp", "confidence": 0.9, "importance": 0.8},
            {"memory_type": "semantic", "content": "Low imp", "confidence": 0.9, "importance": 0.3}
        ]"""

        extractor = MemoryExtractor(config=default_config, llm_func=mock_llm_func)
        messages = [
            {"role": "user", "content": "Test"},
            {"role": "assistant", "content": "OK"},
        ]

        result = await extractor.extract(messages)

        assert len(result.memories) == 1
        assert result.memories[0].content == "High imp"

    @pytest.mark.asyncio
    async def test_respects_max_extractions_limit(self, default_config, mock_llm_func):
        """Test max_extractions_per_turn limit."""
        mock_llm_func.return_value = """[
            {"memory_type": "semantic", "content": "Fact 1", "confidence": 0.9, "importance": 0.8},
            {"memory_type": "semantic", "content": "Fact 2", "confidence": 0.9, "importance": 0.8},
            {"memory_type": "semantic", "content": "Fact 3", "confidence": 0.9, "importance": 0.8},
            {"memory_type": "semantic", "content": "Fact 4", "confidence": 0.9, "importance": 0.8}
        ]"""

        config = ExtractionConfig(max_extractions_per_turn=2)
        extractor = MemoryExtractor(config=config, llm_func=mock_llm_func)
        messages = [
            {"role": "user", "content": "Test"},
            {"role": "assistant", "content": "OK"},
        ]

        result = await extractor.extract(messages)

        assert len(result.memories) == 2

    @pytest.mark.asyncio
    async def test_filters_disabled_memory_types(self, mock_llm_func):
        """Test filtering disabled memory types."""
        mock_llm_func.return_value = """[
            {"memory_type": "profile", "content": "Profile", "confidence": 0.9, "importance": 0.8,
             "profile_key": "k", "profile_value": "v"},
            {"memory_type": "semantic", "content": "Semantic", "confidence": 0.9, "importance": 0.8},
            {"memory_type": "episodic", "content": "Episodic", "confidence": 0.9, "importance": 0.8}
        ]"""

        config = ExtractionConfig(
            extract_profile=True,
            extract_semantic=False,
            extract_episodic=True,
            extract_procedural=False,
        )
        extractor = MemoryExtractor(config=config, llm_func=mock_llm_func)
        messages = [
            {"role": "user", "content": "Test"},
            {"role": "assistant", "content": "OK"},
        ]

        result = await extractor.extract(messages)

        assert len(result.memories) == 2
        assert result.memories[0].memory_type == MemoryType.PROFILE
        assert result.memories[1].memory_type == MemoryType.EPISODIC

    @pytest.mark.asyncio
    async def test_handles_llm_exception(self, default_config, mock_llm_func):
        """Test graceful handling of LLM exceptions."""
        mock_llm_func.side_effect = Exception("LLM API error")

        extractor = MemoryExtractor(config=default_config, llm_func=mock_llm_func)
        messages = [
            {"role": "user", "content": "Test"},
            {"role": "assistant", "content": "OK"},
        ]

        result = await extractor.extract(messages)

        assert result.memories == []
        assert result.extraction_time_ms == 0.0

    @pytest.mark.asyncio
    async def test_no_llm_function_returns_empty(self, default_config):
        """Test extraction without LLM function returns empty result."""
        extractor = MemoryExtractor(config=default_config, llm_func=None)
        messages = [
            {"role": "user", "content": "Test"},
            {"role": "assistant", "content": "OK"},
        ]

        result = await extractor.extract(messages)

        assert result.memories == []

    @pytest.mark.asyncio
    async def test_passes_context_to_llm(self, default_config, mock_llm_func):
        """Test additional context is passed to LLM."""
        mock_llm_func.return_value = "[]"

        extractor = MemoryExtractor(config=default_config, llm_func=mock_llm_func)
        messages = [{"role": "user", "content": "Test"}]
        context = {"project": "AI Assistant", "timezone": "UTC+8"}

        await extractor.extract(messages, context=context)

        call_args = mock_llm_func.call_args
        prompt_arg = call_args[0][1]
        assert "Additional Context" in prompt_arg
        assert "AI Assistant" in prompt_arg
        assert "UTC+8" in prompt_arg


# ============================================================================
# Concrete Memory Conversion Tests
# ============================================================================


class TestConcreteMemoryConversion:
    """Test to_concrete_memories conversion."""

    def test_convert_profile_memory(self, default_config):
        """Test converting profile memory."""
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            ExtractedMemory,
        )

        extractor = MemoryExtractor(config=default_config)
        extracted = [
            ExtractedMemory(
                memory_type=MemoryType.PROFILE,
                content="User age is 25",
                confidence=0.9,
                importance=0.8,
                profile_key="age",
                profile_value="25",
            )
        ]

        concrete = extractor.to_concrete_memories(extracted)

        assert len(concrete) == 1
        assert isinstance(concrete[0], ProfileEntry)
        assert concrete[0].key == "age"
        assert concrete[0].value == "25"

    def test_convert_semantic_memory(self, default_config):
        """Test converting semantic memory."""
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            ExtractedMemory,
        )

        extractor = MemoryExtractor(config=default_config)
        extracted = [
            ExtractedMemory(
                memory_type=MemoryType.SEMANTIC,
                content="Prefers TypeScript over JavaScript",
                confidence=0.9,
                importance=0.7,
                preference_type="explicit",
                preference_strength=0.8,
            )
        ]

        concrete = extractor.to_concrete_memories(extracted)

        assert len(concrete) == 1
        assert isinstance(concrete[0], SemanticMemory)
        assert concrete[0].content == "Prefers TypeScript over JavaScript"
        assert concrete[0].preference_type == "explicit"
        assert concrete[0].preference_strength == 0.8

    def test_convert_semantic_memory_with_source_error(self, default_config):
        """Test source_error propagation from ExtractedMemory to SemanticMemory."""
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            ExtractedMemory,
        )

        extractor = MemoryExtractor(config=default_config)
        extracted = [
            ExtractedMemory(
                memory_type=MemoryType.SEMANTIC,
                content="Prefers tabs over spaces",
                confidence=0.95,
                importance=0.8,
                source_error="Agent used spaces instead of tabs",
            )
        ]

        concrete = extractor.to_concrete_memories(extracted)

        assert len(concrete) == 1
        assert isinstance(concrete[0], SemanticMemory)
        assert concrete[0].source_error == "Agent used spaces instead of tabs"

    def test_convert_episodic_memory(self, default_config):
        """Test converting episodic memory."""
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            ExtractedMemory,
        )

        extractor = MemoryExtractor(config=default_config)
        extracted = [
            ExtractedMemory(
                memory_type=MemoryType.EPISODIC,
                content="Deployed v2.0 to production on 2026-03-10",
                confidence=0.95,
                importance=0.9,
            )
        ]

        concrete = extractor.to_concrete_memories(extracted)

        assert len(concrete) == 1
        assert isinstance(concrete[0], EpisodicMemory)
        assert concrete[0].content == "Deployed v2.0 to production on 2026-03-10"
        assert concrete[0].event_type == "extracted"

    def test_convert_procedural_memory(self, default_config):
        """Test converting procedural memory."""
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            ExtractedMemory,
        )

        extractor = MemoryExtractor(config=default_config)
        extracted = [
            ExtractedMemory(
                memory_type=MemoryType.PROCEDURAL,
                content="Test before deploy",
                confidence=0.95,
                importance=0.9,
                trigger="before deployment",
                action="run pytest",
            )
        ]

        concrete = extractor.to_concrete_memories(extracted)

        assert len(concrete) == 1
        assert isinstance(concrete[0], ProceduralMemory)
        assert concrete[0].trigger == "before deployment"
        assert concrete[0].action == "run pytest"

    def test_convert_procedural_with_tool_rule_priority(self, default_config):
        """Test that tool_rule_priority propagates through to ProceduralMemory."""
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            ExtractedMemory,
        )

        extractor = MemoryExtractor(config=default_config)
        extracted = [
            ExtractedMemory(
                memory_type=MemoryType.PROCEDURAL,
                content="Never use sudo",
                confidence=1.0,
                importance=1.0,
                trigger="using sudo",
                action="Respect user directive: using sudo",
                tool_name="bash_code_execute_tool",
                tool_rule_priority="critical",
            )
        ]

        concrete = extractor.to_concrete_memories(extracted)

        assert len(concrete) == 1
        proc = concrete[0]
        assert isinstance(proc, ProceduralMemory)
        assert proc.tool_name == "bash_code_execute_tool"
        assert proc.tool_rule_priority.value == "critical"

    def test_convert_procedural_default_priority(self, default_config):
        """Test that missing tool_rule_priority defaults to NORMAL."""
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            ExtractedMemory,
        )

        extractor = MemoryExtractor(config=default_config)
        extracted = [
            ExtractedMemory(
                memory_type=MemoryType.PROCEDURAL,
                content="Always run tests",
                confidence=0.9,
                importance=0.8,
                trigger="before commit",
                action="run tests",
                tool_name="bash_code_execute_tool",
            )
        ]

        concrete = extractor.to_concrete_memories(extracted)

        assert len(concrete) == 1
        proc = concrete[0]
        assert isinstance(proc, ProceduralMemory)
        assert proc.tool_rule_priority.value == "normal"

    def test_skips_invalid_profile_memory(self, default_config):
        """Test skipping profile memory without required fields."""
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            ExtractedMemory,
        )

        extractor = MemoryExtractor(config=default_config)
        extracted = [
            ExtractedMemory(
                memory_type=MemoryType.PROFILE,
                content="Missing key/value",
                confidence=0.9,
                importance=0.8,
            )
        ]

        concrete = extractor.to_concrete_memories(extracted)

        assert len(concrete) == 0

    def test_skips_invalid_procedural_memory(self, default_config):
        """Test skipping procedural memory without trigger/action."""
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            ExtractedMemory,
        )

        extractor = MemoryExtractor(config=default_config)
        extracted = [
            ExtractedMemory(
                memory_type=MemoryType.PROCEDURAL,
                content="Missing trigger",
                confidence=0.9,
                importance=0.8,
            )
        ]

        concrete = extractor.to_concrete_memories(extracted)

        assert len(concrete) == 0

    def test_convert_multiple_mixed_types(self, default_config):
        """Test converting multiple memories of different types."""
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            ExtractedMemory,
        )

        extractor = MemoryExtractor(config=default_config)
        extracted = [
            ExtractedMemory(
                memory_type=MemoryType.PROFILE,
                content="Name",
                confidence=0.9,
                importance=0.8,
                profile_key="name",
                profile_value="Alice",
            ),
            ExtractedMemory(
                memory_type=MemoryType.SEMANTIC,
                content="Likes Python",
                confidence=0.9,
                importance=0.7,
            ),
            ExtractedMemory(
                memory_type=MemoryType.EPISODIC,
                content="Fixed bug",
                confidence=0.9,
                importance=0.8,
            ),
        ]

        concrete = extractor.to_concrete_memories(extracted)

        assert len(concrete) == 3
        assert isinstance(concrete[0], ProfileEntry)
        assert isinstance(concrete[1], SemanticMemory)
        assert isinstance(concrete[2], EpisodicMemory)


# ============================================================================
# Configuration Tests
# ============================================================================


class TestExtractionConfiguration:
    """Test extraction configuration."""

    @pytest.mark.asyncio
    async def test_extraction_mode_configuration(self, mock_llm_func):
        """Test extraction mode configuration."""
        mock_llm_func.return_value = "[]"

        config = ExtractionConfig(mode=ExtractionMode.HYBRID)
        extractor = MemoryExtractor(config=config, llm_func=mock_llm_func)
        messages = [{"role": "user", "content": "Test"}]

        await extractor.extract(messages)

        assert mock_llm_func.called
        call_args = mock_llm_func.call_args
        system_prompt = call_args[0][0]
        assert len(system_prompt) > 0
        assert "You are a strict memory gatekeeper" in system_prompt

    @pytest.mark.asyncio
    async def test_custom_thresholds(self, mock_llm_func):
        """Test custom confidence and importance thresholds."""
        mock_llm_func.return_value = """[
            {"memory_type": "semantic", "content": "A", "confidence": 0.95, "importance": 0.9},
            {"memory_type": "semantic", "content": "B", "confidence": 0.85, "importance": 0.8},
            {"memory_type": "semantic", "content": "C", "confidence": 0.75, "importance": 0.7}
        ]"""

        config = ExtractionConfig(min_confidence=0.9, min_importance=0.85)
        extractor = MemoryExtractor(config=config, llm_func=mock_llm_func)
        messages = [{"role": "user", "content": "Test"}]

        result = await extractor.extract(messages)

        assert len(result.memories) == 1
        assert result.memories[0].content == "A"

    @pytest.mark.asyncio
    async def test_disabled_all_types_returns_empty(self, mock_llm_func):
        """Test disabling all memory types returns empty system prompt."""
        mock_llm_func.return_value = "[]"

        config = ExtractionConfig(
            extract_profile=False,
            extract_semantic=False,
            extract_episodic=False,
            extract_procedural=False,
        )
        extractor = MemoryExtractor(config=config, llm_func=mock_llm_func)
        messages = [{"role": "user", "content": "Test"}]

        await extractor.extract(messages)

        call_args = mock_llm_func.call_args
        system_prompt = call_args[0][0]
        assert "Empty array" in system_prompt


# ============================================================================
# Correction Prompt Tests
# ============================================================================


class TestCorrectionPromptBuilding:
    """Test _build_system_prompt correction-related sections."""

    def test_reflection_section_always_included(self):
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            _build_system_prompt,
        )

        config = ExtractionConfig()
        prompt = _build_system_prompt(config, correction_detected=False)
        assert "Structured Reflection" in prompt
        assert "Error/Retry" in prompt
        assert "User Correction" in prompt

    def test_correction_hint_included_when_detected(self):
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            _build_system_prompt,
        )

        config = ExtractionConfig()
        prompt = _build_system_prompt(config, correction_detected=True)
        assert "Explicit correction signals were detected" in prompt
        assert "source_error" in prompt

    def test_correction_hint_absent_when_not_detected(self):
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            _build_system_prompt,
        )

        config = ExtractionConfig()
        prompt = _build_system_prompt(config, correction_detected=False)
        assert "Explicit correction signals were detected" not in prompt


# ============================================================================
# Extraction Quality Rules Tests
# ============================================================================


class TestExtractionQualityRules:
    """Regression tests for extraction quality prompt rules."""

    def test_third_person_rule_present(self):
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            _build_system_prompt,
        )

        prompt = _build_system_prompt(ExtractionConfig())
        assert "Third Person" in prompt
        assert "no pronouns" in prompt.lower()

    def test_outcomes_rule_present(self):
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            _build_system_prompt,
        )

        prompt = _build_system_prompt(ExtractionConfig())
        assert "Outcomes" in prompt
        assert "WAS DONE" in prompt

    def test_conciseness_rule_present(self):
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            _build_system_prompt,
        )

        prompt = _build_system_prompt(ExtractionConfig())
        assert "Concise" in prompt
        assert "15-50 words" in prompt

    def test_never_store_blacklist_present(self):
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            _build_system_prompt,
        )

        prompt = _build_system_prompt(ExtractionConfig())
        assert "Never store" in prompt
        assert "raw tool output" in prompt
        assert "cron heartbeats" in prompt
        assert "acknowledgments" in prompt

    def test_quality_rules_absent_when_no_types_enabled(self):
        """Quality rules are part of core prompt, not shown when all types disabled."""
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            _build_system_prompt,
        )

        config = ExtractionConfig(
            extract_profile=False,
            extract_semantic=False,
            extract_episodic=False,
            extract_procedural=False,
        )
        prompt = _build_system_prompt(config)
        assert "Empty array" in prompt
        assert "Third Person" not in prompt


# ============================================================================
# Edge Cases Tests
# ============================================================================


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_conversation(self, default_config, mock_llm_func):
        """Test extraction from empty conversation."""
        mock_llm_func.return_value = "[]"

        extractor = MemoryExtractor(config=default_config, llm_func=mock_llm_func)
        messages = []

        result = await extractor.extract(messages)

        assert result.memories == []

    @pytest.mark.asyncio
    async def test_single_message(self, default_config, mock_llm_func):
        """Test extraction from single message."""
        mock_llm_func.return_value = """[
            {"memory_type": "semantic", "content": "Likes Python", "confidence": 0.9, "importance": 0.7}
        ]"""

        extractor = MemoryExtractor(config=default_config, llm_func=mock_llm_func)
        messages = [{"role": "user", "content": "I like Python"}]

        result = await extractor.extract(messages)

        assert len(result.memories) == 1

    @pytest.mark.asyncio
    async def test_long_conversation(self, default_config, mock_llm_func):
        """Test extraction from long conversation."""
        mock_llm_func.return_value = """[
            {"memory_type": "semantic", "content": "Project info", "confidence": 0.9, "importance": 0.8}
        ]"""

        extractor = MemoryExtractor(config=default_config, llm_func=mock_llm_func)
        messages = [{"role": "user", "content": f"Message {i}"} for i in range(10)] + [
            {"role": "assistant", "content": f"Response {i}"} for i in range(10)
        ]

        await extractor.extract(messages)

        assert mock_llm_func.called
        call_args = mock_llm_func.call_args
        prompt = call_args[0][1]
        assert "Message 0" in prompt
        assert "Message 9" in prompt

    @pytest.mark.asyncio
    async def test_malformed_memory_skipped(self, default_config, mock_llm_func):
        """Test malformed memory objects are skipped."""
        mock_llm_func.return_value = """[
            {"memory_type": "invalid_type", "content": "Bad", "confidence": 0.9},
            {"memory_type": "semantic", "content": "Good", "confidence": 0.9, "importance": 0.8}
        ]"""

        extractor = MemoryExtractor(config=default_config, llm_func=mock_llm_func)
        messages = [{"role": "user", "content": "Test"}]

        result = await extractor.extract(messages)

        assert len(result.memories) == 1
        assert result.memories[0].content == "Good"

    @pytest.mark.asyncio
    async def test_multimodal_message_content(self, default_config, mock_llm_func):
        """Test handling messages with multimodal content."""
        mock_llm_func.return_value = "[]"

        extractor = MemoryExtractor(config=default_config, llm_func=mock_llm_func)
        messages = [
            {"role": "user", "content": "Analyze this image"},
            {"role": "assistant", "content": "I see a cat in the image"},
        ]

        await extractor.extract(messages)

        mock_llm_func.assert_called_once()


# ============================================================================
# Integration Tests
# ============================================================================


class TestMemoryExtractionIntegration:
    """Test memory extraction in realistic scenarios."""

    @pytest.mark.asyncio
    async def test_chinese_conversation(self, default_config, mock_llm_func):
        """Test extraction from Chinese conversation."""
        mock_llm_func.return_value = """[
            {
                "memory_type": "profile",
                "content": "用户名是张三",
                "confidence": 0.95,
                "importance": 0.9,
                "profile_key": "name",
                "profile_value": "张三"
            }
        ]"""

        extractor = MemoryExtractor(config=default_config, llm_func=mock_llm_func)
        messages = [
            {"role": "user", "content": "我叫张三"},
            {"role": "assistant", "content": "你好，张三！"},
        ]

        result = await extractor.extract(messages)

        assert len(result.memories) == 1
        assert "张三" in result.memories[0].profile_value

    @pytest.mark.asyncio
    async def test_mixed_language_conversation(self, default_config, mock_llm_func):
        """Test extraction from mixed Chinese-English conversation."""
        mock_llm_func.return_value = """[
            {
                "memory_type": "semantic",
                "content": "Uses Python 3.11 for backend development",
                "confidence": 0.9,
                "importance": 0.8
            }
        ]"""

        extractor = MemoryExtractor(config=default_config, llm_func=mock_llm_func)
        messages = [
            {"role": "user", "content": "我在用 Python 3.11 开发后端"},
            {"role": "assistant", "content": "Python 3.11 is a good choice!"},
        ]

        result = await extractor.extract(messages)

        assert len(result.memories) == 1
        assert "Python 3.11" in result.memories[0].content

    @pytest.mark.asyncio
    async def test_technical_details_preserved(self, default_config, mock_llm_func):
        """Test technical details are preserved verbatim."""
        mock_llm_func.return_value = """[
            {
                "memory_type": "semantic",
                "content": "Uses LiteLLM 1.77.2 with max_retries=5 for OpenAI API",
                "confidence": 0.95,
                "importance": 0.8
            }
        ]"""

        extractor = MemoryExtractor(config=default_config, llm_func=mock_llm_func)
        messages = [
            {
                "role": "user",
                "content": "I configure LiteLLM 1.77.2 with max_retries=5",
            },
            {"role": "assistant", "content": "Good configuration"},
        ]

        result = await extractor.extract(messages)

        assert len(result.memories) == 1
        content = result.memories[0].content
        assert "1.77.2" in content
        assert "max_retries=5" in content

    @pytest.mark.asyncio
    async def test_multiple_facts_extracted_separately(
        self, default_config, mock_llm_func
    ):
        """Test multiple facts are extracted as separate memories."""
        mock_llm_func.return_value = """[
            {"memory_type": "semantic", "content": "Likes Python", "confidence": 0.9, "importance": 0.7},
            {"memory_type": "semantic", "content": "Likes TypeScript", "confidence": 0.9, "importance": 0.7},
            {"memory_type": "semantic", "content": "Likes Rust", "confidence": 0.9, "importance": 0.7}
        ]"""

        extractor = MemoryExtractor(config=default_config, llm_func=mock_llm_func)
        messages = [
            {"role": "user", "content": "I like Python, TypeScript, and Rust"},
            {"role": "assistant", "content": "All great languages!"},
        ]

        result = await extractor.extract(messages)

        assert len(result.memories) == 3


# ============================================================================
# Task Digest Tests
# ============================================================================


class TestTaskDigest:
    """Tests for task_digest extraction, filtering, and conversion."""

    @pytest.fixture
    def digest_config(self) -> ExtractionConfig:
        return ExtractionConfig(
            enable_task_digest=True, min_confidence=0.7, min_importance=0.5
        )

    @pytest.fixture
    def digest_llm_response(self) -> str:
        return """[
            {"memory_type": "semantic", "content": "User prefers Python", "confidence": 0.9, "importance": 0.7},
            {
                "memory_type": "task_digest",
                "content": "**Title**: Implement auth module\\n**Goal**: Add JWT auth\\n**Result**: Completed\\n**Key Details**: auth/jwt.py created",
                "confidence": 0.9,
                "importance": 0.85
            }
        ]"""

    @pytest.mark.asyncio
    async def test_digest_extracted_alongside_fragments(
        self, digest_config, digest_llm_response
    ):
        llm = AsyncMock(return_value=digest_llm_response)
        extractor = MemoryExtractor(config=digest_config, llm_func=llm)
        result = await extractor.extract(
            [
                {"role": "user", "content": "Implement JWT auth"},
                {"role": "assistant", "content": "Done."},
            ],
            "local",
        )
        types = [m.memory_type for m in result.memories]
        assert MemoryType.TASK_DIGEST in types
        assert MemoryType.SEMANTIC in types

    @pytest.mark.asyncio
    async def test_digest_not_counted_in_max_extractions(self, digest_config):
        digest_config.max_extractions_per_turn = 1
        llm = AsyncMock(
            return_value="""[
            {"memory_type": "semantic", "content": "Fact A", "confidence": 0.9, "importance": 0.7},
            {"memory_type": "semantic", "content": "Fact B", "confidence": 0.9, "importance": 0.7},
            {"memory_type": "task_digest", "content": "**Title**: Test", "confidence": 0.9, "importance": 0.85}
        ]"""
        )
        extractor = MemoryExtractor(config=digest_config, llm_func=llm)
        result = await extractor.extract(
            [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}],
            "local",
        )
        fragments = [
            m for m in result.memories if m.memory_type != MemoryType.TASK_DIGEST
        ]
        digests = [
            m for m in result.memories if m.memory_type == MemoryType.TASK_DIGEST
        ]
        assert len(fragments) == 1
        assert len(digests) == 1

    @pytest.mark.asyncio
    async def test_digest_limited_to_one(self, digest_config):
        llm = AsyncMock(
            return_value="""[
            {"memory_type": "task_digest", "content": "Digest 1", "confidence": 0.9, "importance": 0.85},
            {"memory_type": "task_digest", "content": "Digest 2", "confidence": 0.9, "importance": 0.85}
        ]"""
        )
        extractor = MemoryExtractor(config=digest_config, llm_func=llm)
        result = await extractor.extract(
            [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}],
            "local",
        )
        digests = [
            m for m in result.memories if m.memory_type == MemoryType.TASK_DIGEST
        ]
        assert len(digests) == 1

    @pytest.mark.asyncio
    async def test_digest_exempt_from_min_importance_filter(self, digest_config):
        digest_config.min_importance = 0.9
        llm = AsyncMock(
            return_value="""[
            {"memory_type": "semantic", "content": "Low fact", "confidence": 0.9, "importance": 0.6},
            {"memory_type": "task_digest", "content": "**Title**: Task", "confidence": 0.9, "importance": 0.85}
        ]"""
        )
        extractor = MemoryExtractor(config=digest_config, llm_func=llm)
        result = await extractor.extract(
            [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}],
            "local",
        )
        assert len(result.memories) == 1
        assert result.memories[0].memory_type == MemoryType.TASK_DIGEST

    @pytest.mark.asyncio
    async def test_digest_excluded_when_disabled(self):
        config = ExtractionConfig(enable_task_digest=False)
        llm = AsyncMock(
            return_value="""[
            {"memory_type": "task_digest", "content": "Should not appear", "confidence": 0.9, "importance": 0.85}
        ]"""
        )
        extractor = MemoryExtractor(config=config, llm_func=llm)
        result = await extractor.extract(
            [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}],
            "local",
        )
        assert len(result.memories) == 0

    def test_digest_prompt_section_included_when_enabled(self, digest_config):
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            _build_system_prompt,
        )

        prompt = _build_system_prompt(digest_config)
        assert "Task Digest" in prompt
        assert "task_digest" in prompt

    def test_digest_prompt_section_absent_when_disabled(self):
        config = ExtractionConfig(enable_task_digest=False)
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            _build_system_prompt,
        )

        prompt = _build_system_prompt(config)
        assert "Task Digest" not in prompt

    def test_digest_converts_to_episodic_memory(self, digest_config):
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            ExtractedMemory,
        )

        extracted = [
            ExtractedMemory(
                memory_type=MemoryType.TASK_DIGEST,
                content="**Title**: Auth\\n**Goal**: JWT\\n**Result**: Done",
                confidence=0.9,
                importance=0.85,
            )
        ]
        extractor = MemoryExtractor(config=digest_config)
        concrete = extractor.to_concrete_memories(extracted, source_chat_id="chat_1")
        assert len(concrete) == 1
        mem = concrete[0]
        assert isinstance(mem, EpisodicMemory)
        assert mem.event_type == "task_digest"
        assert mem.importance == 0.85
        assert mem.source_chat_id == "chat_1"
        assert mem.lifecycle is not None
        assert mem.lifecycle.tier == MemoryTier.L2
        assert mem.lifecycle.digest_kind == DigestKind.TASK
        assert mem.lifecycle.evaporation_state == EvaporationState.PENDING
        assert mem.lifecycle.claim_graph_state == ClaimGraphState.PENDING
        assert mem.lifecycle.claim_graph_conflict == ClaimConflictState.NONE

    @pytest.mark.asyncio
    async def test_empty_content_digest_discarded(self, digest_config):
        llm = AsyncMock(
            return_value="""[
            {"memory_type": "task_digest", "content": "", "confidence": 0.9, "importance": 0.85},
            {"memory_type": "task_digest", "content": "  ", "confidence": 0.9, "importance": 0.85}
        ]"""
        )
        extractor = MemoryExtractor(config=digest_config, llm_func=llm)
        result = await extractor.extract(
            [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
            ],
            "local",
        )
        digests = [
            m for m in result.memories if m.memory_type == MemoryType.TASK_DIGEST
        ]
        assert len(digests) == 0


# ============================================================================
# Extraction Correction Metrics Tests
# ============================================================================


class TestExtractionCorrectionMetrics:
    """Test correction_signal_detected and correction_count in ExtractionResult."""

    @pytest.mark.asyncio
    async def test_correction_metrics_populated(self, default_config):
        llm = AsyncMock(
            return_value="""[
            {"memory_type": "semantic", "content": "Use uv sync", "confidence": 0.95,
             "importance": 0.9, "source_error": "Agent used pip install"}
        ]"""
        )
        extractor = MemoryExtractor(config=default_config, llm_func=llm)
        result = await extractor.extract(
            [{"role": "user", "content": "你搞错了，应该用 uv sync"}],
            "local",
            correction_detected=True,
        )
        assert result.correction_signal_detected is True
        assert result.correction_count == 1

    @pytest.mark.asyncio
    async def test_no_correction_signal(self, default_config):
        llm = AsyncMock(
            return_value="""[
            {"memory_type": "semantic", "content": "Likes Python", "confidence": 0.9, "importance": 0.7}
        ]"""
        )
        extractor = MemoryExtractor(config=default_config, llm_func=llm)
        result = await extractor.extract(
            [{"role": "user", "content": "I like Python"}],
            "local",
            correction_detected=False,
        )
        assert result.correction_signal_detected is False
        assert result.correction_count == 0

    @pytest.mark.asyncio
    async def test_correction_detected_but_no_source_error(self, default_config):
        """When correction detected but LLM didn't fill source_error → WARNING logged."""
        llm = AsyncMock(
            return_value="""[
            {"memory_type": "semantic", "content": "Use tabs", "confidence": 0.9, "importance": 0.8}
        ]"""
        )
        extractor = MemoryExtractor(config=default_config, llm_func=llm)
        result = await extractor.extract(
            [{"role": "user", "content": "不对，用 tabs"}],
            "local",
            correction_detected=True,
        )
        assert result.correction_signal_detected is True
        assert result.correction_count == 0

    def test_default_extraction_result_metrics(self):
        result = ExtractionResult()
        assert result.correction_signal_detected is False
        assert result.correction_count == 0


# ============================================================================
# Truncation Tests
# ============================================================================


class TestTruncateMessagesHeadTail:
    """Tests for _truncate_messages_head_tail."""

    def test_short_conversation_no_truncation(self):
        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result, dropped = _truncate_messages_head_tail(msgs, max_chars=1000)
        assert result == msgs
        assert dropped == 0

    def test_truncation_preserves_head_and_tail(self):
        head = [
            {"role": "user", "content": "A" * 100},
            {"role": "assistant", "content": "B" * 100},
        ]
        mid = [{"role": "user", "content": "M" * 200} for _ in range(5)]
        tail = [{"role": "user", "content": "Z" * 100}]
        msgs = head + mid + tail
        result, dropped = _truncate_messages_head_tail(msgs, max_chars=400)
        assert result[0]["content"] == "A" * 100
        assert result[1]["content"] == "B" * 100
        assert result[-1]["content"] == "Z" * 100
        assert dropped > 0
        assert any("omitted" in m.get("content", "") for m in result)

    def test_truncation_marker_contains_count(self):
        msgs = [{"role": "user", "content": "X" * 50} for _ in range(10)]
        result, dropped = _truncate_messages_head_tail(msgs, max_chars=200)
        marker = [m for m in result if "omitted" in m.get("content", "")]
        assert len(marker) == 1
        assert str(dropped) in marker[0]["content"]

    def test_exactly_at_limit_no_truncation(self):
        msgs = [
            {"role": "user", "content": "A" * 50},
            {"role": "assistant", "content": "B" * 50},
        ]
        result, dropped = _truncate_messages_head_tail(msgs, max_chars=100)
        assert dropped == 0
        assert len(result) == 2

    def test_single_message_no_crash(self):
        msgs = [{"role": "user", "content": "X" * 200}]
        result, dropped = _truncate_messages_head_tail(msgs, max_chars=100)
        assert result[0]["content"] == "X" * 200
        assert dropped == 0

    def test_head_exceeds_limit_with_extra_messages(self):
        """When the first 2 messages already exceed max_chars, tail is empty but
        middle messages are still marked as dropped."""
        head = [
            {"role": "user", "content": "A" * 500},
            {"role": "assistant", "content": "B" * 500},
        ]
        extra = [{"role": "user", "content": "C" * 100} for _ in range(3)]
        msgs = head + extra
        result, dropped = _truncate_messages_head_tail(msgs, max_chars=200)
        assert dropped == 3
        assert result[0]["content"] == "A" * 500
        assert result[1]["content"] == "B" * 500
        assert any("omitted" in m.get("content", "") for m in result)
        assert len(result) == 3  # head(2) + marker(1)


class TestExtractTruncation:
    """Integration test: extract() populates truncated/dropped_message_count."""

    @pytest.mark.asyncio
    async def test_extract_with_truncation(self):
        llm = AsyncMock(return_value="[]")
        config = ExtractionConfig(max_input_chars=100)
        extractor = MemoryExtractor(config=config, llm_func=llm)
        msgs = [{"role": "user", "content": "X" * 50} for _ in range(10)]
        result = await extractor.extract(msgs)
        assert result.truncated is True
        assert result.dropped_message_count > 0

    @pytest.mark.asyncio
    async def test_extract_without_truncation(self):
        llm = AsyncMock(return_value="[]")
        config = ExtractionConfig(max_input_chars=100_000)
        extractor = MemoryExtractor(config=config, llm_func=llm)
        msgs = [{"role": "user", "content": "hello"}]
        result = await extractor.extract(msgs)
        assert result.truncated is False
        assert result.dropped_message_count == 0


# ============================================================================
# Session date injection in user prompt (Temporal Grounding)
# ============================================================================


class TestSessionDateInjection:
    """Verify extract() injects Session date into the LLM user prompt."""

    @pytest.mark.asyncio
    async def test_user_prompt_contains_session_date(self):
        captured_prompt: list[str] = []

        async def capture_llm(_system: str, user: str) -> str:
            captured_prompt.append(user)
            return "[]"

        config = ExtractionConfig()
        extractor = MemoryExtractor(config=config, llm_func=capture_llm)
        msgs = [{"role": "user", "content": "I had a meeting yesterday"}]
        await extractor.extract(msgs)

        assert len(captured_prompt) == 1
        prompt = captured_prompt[0]
        assert prompt.startswith("Session date: ")
        import re

        match = re.search(r"Session date: (\d{4}-\d{2}-\d{2}) \((\w+)\)", prompt)
        assert match, f"Expected YYYY-MM-DD (Weekday) format, got: {prompt[:80]}"

    @pytest.mark.asyncio
    async def test_system_prompt_does_not_contain_dynamic_date(self):
        captured_system: list[str] = []

        async def capture_llm(system: str, _user: str) -> str:
            captured_system.append(system)
            return "[]"

        config = ExtractionConfig()
        extractor = MemoryExtractor(config=config, llm_func=capture_llm)
        msgs = [{"role": "user", "content": "hello"}]
        await extractor.extract(msgs)

        assert len(captured_system) == 1
        import re

        assert not re.search(
            r"\d{4}-\d{2}-\d{2}", captured_system[0]
        ), "System prompt must NOT contain dynamic dates (cache-breaking)"

    @pytest.mark.asyncio
    async def test_weekday_is_english(self):
        """Weekday in Session date must be English regardless of system locale."""
        captured_prompt: list[str] = []

        async def capture_llm(_system: str, user: str) -> str:
            captured_prompt.append(user)
            return "[]"

        extractor = MemoryExtractor(config=ExtractionConfig(), llm_func=capture_llm)
        await extractor.extract([{"role": "user", "content": "test"}])

        import re

        match = re.search(r"Session date: \d{4}-\d{2}-\d{2} \((\w+)\)", captured_prompt[0])
        assert match
        weekday = match.group(1)
        valid_weekdays = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"}
        assert weekday in valid_weekdays, f"Expected English weekday, got: {weekday}"

    @pytest.mark.asyncio
    async def test_date_present_with_correction_detected(self):
        """Session date injected even when correction_detected=True."""
        captured_prompt: list[str] = []

        async def capture_llm(_system: str, user: str) -> str:
            captured_prompt.append(user)
            return "[]"

        extractor = MemoryExtractor(config=ExtractionConfig(), llm_func=capture_llm)
        msgs = [
            {"role": "user", "content": "No, I said Python not Java"},
            {"role": "assistant", "content": "Sorry, Python it is"},
        ]
        await extractor.extract(msgs, correction_detected=True)

        assert captured_prompt[0].startswith("Session date: ")

    @pytest.mark.asyncio
    async def test_date_present_with_context(self):
        """Session date injected when additional context is provided."""
        captured_prompt: list[str] = []

        async def capture_llm(_system: str, user: str) -> str:
            captured_prompt.append(user)
            return "[]"

        extractor = MemoryExtractor(config=ExtractionConfig(), llm_func=capture_llm)
        msgs = [{"role": "user", "content": "I use VS Code"}]
        await extractor.extract(msgs, context={"project": "myrm"})

        prompt = captured_prompt[0]
        assert prompt.startswith("Session date: ")
        assert "Additional Context" in prompt

    @pytest.mark.asyncio
    async def test_date_present_after_truncation(self):
        """Session date survives message truncation (injected after truncation)."""
        captured_prompt: list[str] = []

        async def capture_llm(_system: str, user: str) -> str:
            captured_prompt.append(user)
            return "[]"

        config = ExtractionConfig(max_input_chars=100)
        extractor = MemoryExtractor(config=config, llm_func=capture_llm)
        msgs = [{"role": "user", "content": "X" * 50} for _ in range(10)]
        await extractor.extract(msgs)

        assert captured_prompt[0].startswith("Session date: ")


# ============================================================================
# auto_extract_memories — auto-feedback integration
# ============================================================================


class TestAutoExtractFeedbackIntegration:
    """Test the auto-feedback rating logic inside auto_extract_memories."""

    @staticmethod
    def _mock_manager(cited_ids: list[str] | None = None):
        mgr = AsyncMock()
        mgr.user_id = "local"
        mgr.last_cited_memory_ids = cited_ids or []
        mgr.set_last_cited_memory_ids = lambda ids: None
        mgr.rate_memory = AsyncMock()
        mgr.store_batch = AsyncMock(return_value=[])
        return mgr

    @staticmethod
    def _mock_llm():
        llm = AsyncMock()
        llm.ainvoke = AsyncMock(return_value=AsyncMock(content="[]"))
        return llm

    @pytest.mark.asyncio
    async def test_positive_feedback_rates_cited_memories(self):
        from myrm_agent_harness.agent._internals.memory_extraction import (
            auto_extract_memories,
        )

        mgr = self._mock_manager(cited_ids=["m1", "m2"])
        llm = self._mock_llm()
        await auto_extract_memories(
            query="太好了，记得很准",
            chat_history=None,
            memory_manager=mgr,
            llm=llm,
            assistant_reply="你好小明！" * 30,
            enable_verbatim=False,
        )
        assert mgr.rate_memory.call_count == 2
        mgr.rate_memory.assert_any_call("m1", 5)
        mgr.rate_memory.assert_any_call("m2", 5)

    @pytest.mark.asyncio
    async def test_negative_feedback_rates_score_1(self):
        from myrm_agent_harness.agent._internals.memory_extraction import (
            auto_extract_memories,
        )

        mgr = self._mock_manager(cited_ids=["m1"])
        llm = self._mock_llm()
        await auto_extract_memories(
            query="不对，你记错了",
            chat_history=None,
            memory_manager=mgr,
            llm=llm,
            assistant_reply="你好！" * 30,
            enable_verbatim=False,
        )
        mgr.rate_memory.assert_called_once_with("m1", 1)

    @pytest.mark.asyncio
    async def test_no_feedback_skips_rating(self):
        from myrm_agent_harness.agent._internals.memory_extraction import (
            auto_extract_memories,
        )

        mgr = self._mock_manager(cited_ids=["m1"])
        llm = self._mock_llm()
        await auto_extract_memories(
            query="今天天气怎么样？",
            chat_history=None,
            memory_manager=mgr,
            llm=llm,
            assistant_reply="天气晴朗。" * 30,
            enable_verbatim=False,
        )
        mgr.rate_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_cited_ids_skips_rating(self):
        from myrm_agent_harness.agent._internals.memory_extraction import (
            auto_extract_memories,
        )

        mgr = self._mock_manager(cited_ids=[])
        llm = self._mock_llm()
        await auto_extract_memories(
            query="太好了，非常棒",
            chat_history=None,
            memory_manager=mgr,
            llm=llm,
            assistant_reply="谢谢！" * 30,
            enable_verbatim=False,
        )
        mgr.rate_memory.assert_not_called()

    @pytest.mark.asyncio
    async def test_rate_failure_continues(self):
        from myrm_agent_harness.agent._internals.memory_extraction import (
            auto_extract_memories,
        )

        mgr = self._mock_manager(cited_ids=["m1", "m2", "m3"])
        mgr.rate_memory = AsyncMock(side_effect=[None, ValueError("not found"), None])
        llm = self._mock_llm()
        await auto_extract_memories(
            query="太好了，记得很准",
            chat_history=None,
            memory_manager=mgr,
            llm=llm,
            assistant_reply="你好小明！" * 30,
            enable_verbatim=False,
        )
        assert mgr.rate_memory.call_count == 3


# ============================================================================
# extract_memories_from_conversation — regex pre-scan
# ============================================================================


class TestExtractMemoriesFromConversationRegex:
    """Test regex pre-scan in extract_memories_from_conversation."""

    @pytest.mark.asyncio
    async def test_regex_prescan_captures_edict_with_critical_priority(self):
        """Regex pre-scan should produce PROCEDURAL memories with tool_rule_priority='critical'."""
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            extract_memories_from_conversation,
        )

        async def mock_llm(_system: str, _prompt: str) -> str:
            return "[]"

        messages = [
            {"role": "user", "content": "never use sudo for this project."},
            {"role": "assistant", "content": "Understood."},
        ]

        result = await extract_memories_from_conversation(messages, mock_llm)

        procedural = [m for m in result.memories if m.memory_type == MemoryType.PROCEDURAL]
        assert len(procedural) >= 1
        edict = procedural[0]
        assert edict.tool_rule_priority == "critical"
        assert edict.confidence == 1.0
        assert edict.importance == 1.0

    @pytest.mark.asyncio
    async def test_regex_prescan_associates_tool_name(self):
        """Regex pre-scan should associate tool_name via keyword matching."""
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            extract_memories_from_conversation,
        )

        async def mock_llm(_system: str, _prompt: str) -> str:
            return "[]"

        messages = [
            {"role": "user", "content": "禁止使用sudo命令。"},
        ]

        result = await extract_memories_from_conversation(messages, mock_llm)

        procedural = [m for m in result.memories if m.memory_type == MemoryType.PROCEDURAL]
        assert len(procedural) >= 1
        assert procedural[0].tool_name == "bash_code_execute_tool"

    @pytest.mark.asyncio
    async def test_regex_prescan_skips_non_user_messages(self):
        """Regex pre-scan should only scan user messages, not assistant."""
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            extract_memories_from_conversation,
        )

        async def mock_llm(_system: str, _prompt: str) -> str:
            return "[]"

        messages = [
            {"role": "assistant", "content": "never use sudo for this project."},
        ]

        result = await extract_memories_from_conversation(messages, mock_llm)
        procedural = [m for m in result.memories if m.memory_type == MemoryType.PROCEDURAL]
        assert len(procedural) == 0

    @pytest.mark.asyncio
    async def test_regex_prescan_prepended_before_llm_results(self):
        """Regex pre-scan results should come before LLM-extracted results."""
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            extract_memories_from_conversation,
        )

        async def mock_llm(_system: str, _prompt: str) -> str:
            return '[{"memory_type": "semantic", "content": "User likes Python", "confidence": 0.9, "importance": 0.7}]'

        messages = [
            {"role": "user", "content": "never use sudo. I like Python."},
        ]

        result = await extract_memories_from_conversation(messages, mock_llm)
        assert len(result.memories) >= 2
        assert result.memories[0].memory_type == MemoryType.PROCEDURAL
        assert result.memories[0].tool_rule_priority == "critical"


# ============================================================================
# Goal Learnings Extraction Tests
# ============================================================================


class TestGoalLearningsExtraction:
    """Tests for extract_goal_learnings function."""

    @pytest.mark.asyncio
    async def test_extracts_learnings_from_goal_trace(self):
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            extract_goal_learnings,
        )

        async def mock_llm(_system: str, _prompt: str) -> str:
            return """[
                {"memory_type": "semantic", "content": "Always update locale files when modifying i18n components", "confidence": 0.9, "importance": 0.8, "reasoning": "Agent forgot locale sync"},
                {"memory_type": "semantic", "content": "Use bun instead of npm in this project", "confidence": 0.95, "importance": 0.85, "reasoning": "npm failed, bun worked"}
            ]"""

        messages = [
            {"role": "user", "content": "Add i18n support to the settings page"},
            {"role": "assistant", "content": "I'll add i18n support..."},
            {"role": "user", "content": "You forgot to update the locale files!"},
            {"role": "assistant", "content": "Sorry, let me fix that..."},
        ]

        result = await extract_goal_learnings(
            messages=messages,
            goal_objective="Add internationalization support to settings",
            llm_func=mock_llm,
        )
        assert len(result) == 2
        assert "locale files" in result[0].content
        assert result[0].confidence >= 0.7
        assert result[0].importance >= 0.6

    @pytest.mark.asyncio
    async def test_returns_empty_for_short_messages(self):
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            extract_goal_learnings,
        )

        async def mock_llm(_system: str, _prompt: str) -> str:
            return "[]"

        result = await extract_goal_learnings(
            messages=[],
            goal_objective="test",
            llm_func=mock_llm,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_for_empty_objective(self):
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            extract_goal_learnings,
        )

        async def mock_llm(_system: str, _prompt: str) -> str:
            return "[]"

        result = await extract_goal_learnings(
            messages=[{"role": "user", "content": "hello"}],
            goal_objective="",
            llm_func=mock_llm,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_filters_low_confidence_learnings(self):
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            extract_goal_learnings,
        )

        async def mock_llm(_system: str, _prompt: str) -> str:
            return """[
                {"memory_type": "semantic", "content": "Maybe use X", "confidence": 0.4, "importance": 0.3},
                {"memory_type": "semantic", "content": "Always use Y for Z", "confidence": 0.9, "importance": 0.8}
            ]"""

        messages = [
            {"role": "user", "content": "Do something complex"},
            {"role": "assistant", "content": "Done with detailed steps..."},
        ]

        result = await extract_goal_learnings(
            messages=messages,
            goal_objective="Complex task",
            llm_func=mock_llm,
        )
        assert len(result) == 1
        assert "Always use Y" in result[0].content

    @pytest.mark.asyncio
    async def test_graceful_failure_on_llm_error(self):
        from myrm_agent_harness.toolkits.memory.strategies.extractor import (
            extract_goal_learnings,
        )

        async def failing_llm(_system: str, _prompt: str) -> str:
            raise RuntimeError("LLM connection failed")

        messages = [
            {"role": "user", "content": "test"},
            {"role": "assistant", "content": "response"},
        ]

        result = await extract_goal_learnings(
            messages=messages,
            goal_objective="Test objective",
            llm_func=failing_llm,
        )
        assert result == []


# ============================================================================
# Main
# ============================================================================


if __name__ == "__main__":
    asyncio.run(asyncio.gather(*[pytest.main([__file__, "-v", "--tb=short"])]))
