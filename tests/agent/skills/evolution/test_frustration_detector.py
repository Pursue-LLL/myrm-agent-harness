"""Tests for frustration signal detector."""

import pytest

from myrm_agent_harness.agent.skills.evolution.pipeline.frustration_detector import (
    FrustrationCategory,
    FrustrationSignal,
    detect_frustration,
)


class TestDetectFrustration:
    """Test suite for detect_frustration function."""

    def test_returns_none_for_empty_messages(self) -> None:
        assert detect_frustration([]) is None

    def test_returns_none_for_neutral_messages(self) -> None:
        messages = [
            {"role": "user", "content": "How do I set up a Python virtual environment?"},
            {"role": "assistant", "content": "You can use python -m venv..."},
        ]
        assert detect_frustration(messages) is None

    def test_detects_verbosity_english(self) -> None:
        messages = [
            {"role": "assistant", "content": "Here's a detailed explanation..."},
            {"role": "user", "content": "just give me the answer, stop explaining"},
        ]
        result = detect_frustration(messages)
        assert result is not None
        assert result.category == FrustrationCategory.VERBOSITY
        assert "just give me the answer" in result.matched_text

    def test_detects_verbosity_chinese(self) -> None:
        messages = [
            {"role": "user", "content": "太啰嗦了，直接给我代码"},
        ]
        result = detect_frustration(messages)
        assert result is not None
        assert result.category == FrustrationCategory.VERBOSITY

    def test_detects_style_english(self) -> None:
        messages = [
            {"role": "user", "content": "I hate when you add unnecessary boilerplate"},
        ]
        result = detect_frustration(messages)
        assert result is not None
        assert result.category == FrustrationCategory.STYLE

    def test_detects_style_chinese(self) -> None:
        messages = [
            {"role": "user", "content": "以后都别这样写了"},
        ]
        result = detect_frustration(messages)
        assert result is not None
        assert result.category == FrustrationCategory.STYLE

    def test_detects_format_english(self) -> None:
        messages = [
            {"role": "user", "content": "no markdown tables please, plain text only"},
        ]
        result = detect_frustration(messages)
        assert result is not None
        assert result.category == FrustrationCategory.FORMAT

    def test_detects_format_chinese(self) -> None:
        messages = [
            {"role": "user", "content": "不要用markdown表格，纯文本就行"},
        ]
        result = detect_frustration(messages)
        assert result is not None
        assert result.category == FrustrationCategory.FORMAT

    def test_detects_workflow_english(self) -> None:
        messages = [
            {"role": "user", "content": "just do it, stop asking me every time"},
        ]
        result = detect_frustration(messages)
        assert result is not None
        assert result.category == FrustrationCategory.WORKFLOW

    def test_detects_workflow_chinese(self) -> None:
        messages = [
            {"role": "user", "content": "不用每次都问我确认，直接做就行"},
        ]
        result = detect_frustration(messages)
        assert result is not None
        assert result.category == FrustrationCategory.WORKFLOW

    def test_only_scans_user_messages(self) -> None:
        messages = [
            {"role": "assistant", "content": "stop explaining everything"},
            {"role": "system", "content": "just give me the answer"},
        ]
        assert detect_frustration(messages) is None

    def test_scan_window_limit(self) -> None:
        neutral = [{"role": "user", "content": "Hi"}] * 10
        frustration = [{"role": "user", "content": "too verbose, be concise"}]
        messages_old_frustration = frustration + neutral
        assert detect_frustration(messages_old_frustration) is None

        messages_recent_frustration = neutral + frustration
        assert detect_frustration(messages_recent_frustration) is not None

    def test_user_message_truncated_in_signal(self) -> None:
        long_msg = "just give me the answer " + "x" * 1000
        messages = [{"role": "user", "content": long_msg}]
        result = detect_frustration(messages)
        assert result is not None
        assert len(result.user_message) <= 500

    def test_verbosity_stop_explaining(self) -> None:
        messages = [{"role": "user", "content": "Can you stop explaining and just code?"}]
        result = detect_frustration(messages)
        assert result is not None
        assert result.category == FrustrationCategory.VERBOSITY

    def test_style_please_stop(self) -> None:
        messages = [{"role": "user", "content": "please stop adding type hints everywhere"}]
        result = detect_frustration(messages)
        assert result is not None
        assert result.category == FrustrationCategory.STYLE

    def test_general_from_now_on(self) -> None:
        messages = [{"role": "user", "content": "from now on, always use tabs instead of spaces"}]
        result = detect_frustration(messages)
        assert result is not None
        assert result.category == FrustrationCategory.GENERAL

    def test_general_chinese_remember(self) -> None:
        messages = [{"role": "user", "content": "以后注意不要加注释"}]
        result = detect_frustration(messages)
        assert result is not None
        assert result.category == FrustrationCategory.GENERAL

    def test_priority_order_verbosity_over_general(self) -> None:
        messages = [{"role": "user", "content": "from now on, just give me the answer directly"}]
        result = detect_frustration(messages)
        assert result is not None
        assert result.category == FrustrationCategory.VERBOSITY

    def test_does_not_match_positive_feedback(self) -> None:
        messages = [
            {"role": "user", "content": "Great job! That's exactly what I wanted."},
        ]
        assert detect_frustration(messages) is None

    def test_does_not_match_correction(self) -> None:
        messages = [
            {"role": "user", "content": "That's wrong, it should be PostgreSQL not MySQL"},
        ]
        assert detect_frustration(messages) is None


class TestFrustrationSignal:
    """Test FrustrationSignal dataclass properties."""

    def test_frozen_and_hashable(self) -> None:
        sig = FrustrationSignal(
            category=FrustrationCategory.VERBOSITY,
            matched_text="too verbose",
            user_message="This is too verbose",
        )
        assert hash(sig)
        with pytest.raises(AttributeError):
            sig.category = FrustrationCategory.STYLE  # type: ignore[misc]
