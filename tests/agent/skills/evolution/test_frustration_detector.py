"""Tests for frustration_detector — pure-CPU regex-based detection.

Covers: all 5 FrustrationCategory types, English + Chinese patterns,
boundary cases (empty, no user messages, no match).
"""

import pytest

from myrm_agent_harness.agent.skills.evolution.pipeline.frustration_detector import (
    FrustrationCategory,
    FrustrationSignal,
    detect_frustration,
)


class TestVerbosityDetection:
    """Verbosity frustration patterns (EN + ZH)."""

    @pytest.mark.parametrize(
        "text",
        [
            "just give me the answer",
            "Just give me the code please",
            "stop explaining and do it",
            "too verbose, cut it down",
            "too much text already",
            "don't need explaining this",
            "skip the preamble",
            "get to the point",
            "why are you explaining this?",
            "太啰嗦",
            "太冗长了",
            "别说那么多废话",
            "直接给我代码",
            "简洁一点",
            "废话太多",
            "多余的解释不需要",
        ],
    )
    def test_detects_verbosity(self, text: str) -> None:
        msgs = [{"role": "user", "content": text}]
        result = detect_frustration(msgs)
        assert result is not None
        assert result.category == FrustrationCategory.VERBOSITY


class TestStyleDetection:
    """Style frustration patterns (EN + ZH)."""

    @pytest.mark.parametrize(
        "text",
        [
            "stop doing that every time",
            "you always do this wrong",
            "I hate when you add comments",
            "don't do that again",
            "please stop",
            "I've told you many times",
            "how many times do I need to say",
            "别再这样做了",
            "以后都不要这样",
            "说了好几次了",
            "你总是犯这个错误",
            "烦死了",
            "每次都这样搞",
        ],
    )
    def test_detects_style(self, text: str) -> None:
        msgs = [{"role": "user", "content": text}]
        result = detect_frustration(msgs)
        assert result is not None
        assert result.category == FrustrationCategory.STYLE


class TestFormatDetection:
    """Format frustration patterns (EN + ZH)."""

    @pytest.mark.parametrize(
        "text",
        [
            "don't use markdown tables",
            "no markdown please",
            "plain text only",
            "stop using emojis",
            "不要用表格",
            "别格式化了",
            "纯文本就行",
            "不要加emoji",
        ],
    )
    def test_detects_format(self, text: str) -> None:
        msgs = [{"role": "user", "content": text}]
        result = detect_frustration(msgs)
        assert result is not None
        assert result.category == FrustrationCategory.FORMAT


class TestWorkflowDetection:
    """Workflow frustration patterns (EN + ZH)."""

    @pytest.mark.parametrize(
        "text",
        [
            "don't ask me every time",
            "just do it",
            "stop asking",
            "don't wait for me to confirm",
            "别总是问我",
            "直接做就行",
            "不用等我确认",
        ],
    )
    def test_detects_workflow(self, text: str) -> None:
        msgs = [{"role": "user", "content": text}]
        result = detect_frustration(msgs)
        assert result is not None
        assert result.category == FrustrationCategory.WORKFLOW


class TestGeneralDetection:
    """General frustration patterns (EN + ZH)."""

    @pytest.mark.parametrize(
        "text",
        [
            "from now on do it differently",
            "never do that again",
            "以后注意这一点",
            "以后记住了",
        ],
    )
    def test_detects_general(self, text: str) -> None:
        msgs = [{"role": "user", "content": text}]
        result = detect_frustration(msgs)
        assert result is not None
        assert result.category == FrustrationCategory.GENERAL


class TestNegativeCases:
    """No false positives on normal conversation."""

    @pytest.mark.parametrize(
        "text",
        [
            "Please help me write a Python script",
            "Can you explain how async works?",
            "What's the best way to deploy this?",
            "Thanks, that worked perfectly!",
            "请帮我写一个爬虫",
            "这个函数怎么用？",
            "谢谢，解决了",
            "",
        ],
    )
    def test_no_false_positive(self, text: str) -> None:
        msgs = [{"role": "user", "content": text}]
        result = detect_frustration(msgs)
        assert result is None


class TestEdgeCases:
    """Edge cases: empty, no user, assistant-only, scan window."""

    def test_empty_messages(self) -> None:
        assert detect_frustration([]) is None

    def test_no_user_messages(self) -> None:
        msgs = [{"role": "assistant", "content": "too verbose output here"}]
        assert detect_frustration(msgs) is None

    def test_only_scans_last_window(self) -> None:
        old = [{"role": "user", "content": "太啰嗦"}]
        filler = [{"role": "user", "content": f"normal message {i}"} for i in range(5)]
        result = detect_frustration(old + filler)
        assert result is None

    def test_result_has_correct_fields(self) -> None:
        msgs = [{"role": "user", "content": "stop explaining already!"}]
        result = detect_frustration(msgs)
        assert isinstance(result, FrustrationSignal)
        assert result.matched_text
        assert result.user_message == "stop explaining already!"

    def test_message_truncation(self) -> None:
        long_msg = "太啰嗦" + "x" * 1000
        msgs = [{"role": "user", "content": long_msg}]
        result = detect_frustration(msgs)
        assert result is not None
        assert len(result.user_message) <= 500
