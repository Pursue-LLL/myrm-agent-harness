"""Tests for myrm_agent_harness.utils.text_sanitizer."""

import pytest

from myrm_agent_harness.agent.streaming.reasoning_scrubber import THINKING_TAG_NAMES
from myrm_agent_harness.utils.text_sanitizer import (
    extract_and_strip_think_blocks,
    sanitize_llm_output,
    sanitize_text,
)


class TestExtractAndStripThinkBlocks:
    def test_empty_string(self) -> None:
        assert extract_and_strip_think_blocks("") == ("", "")

    def test_normal_text(self) -> None:
        text = "Just normal text without tags."
        clean, reasoning = extract_and_strip_think_blocks(text)
        assert clean == text
        assert reasoning == ""

    def test_single_think_block(self) -> None:
        text = "<think>some reasoning</think>The actual answer"
        clean, reasoning = extract_and_strip_think_blocks(text)
        assert clean == "The actual answer"
        assert reasoning == "some reasoning"

    def test_multiple_think_blocks(self) -> None:
        text = "<think>first thought</think>Middle<thought>second thought</thought>End"
        clean, reasoning = extract_and_strip_think_blocks(text)
        assert clean == "MiddleEnd"
        assert reasoning == "first thought\n\nsecond thought"

    def test_orphan_tags(self) -> None:
        text = "</think>Just text<think>reason</think><thought>"
        clean, reasoning = extract_and_strip_think_blocks(text)
        assert clean == "Just text"
        assert reasoning == "reason"

    def test_sanitizes_control_characters(self) -> None:
        text = "<think>reason\x00</think>clean\ufffd"
        clean, reasoning = extract_and_strip_think_blocks(text)
        assert clean == "clean"
        assert reasoning == "reason"


    @pytest.mark.parametrize("tag_name", THINKING_TAG_NAMES)
    def test_all_tag_names_extracted(self, tag_name: str) -> None:
        text = f"before<{tag_name}>inner</{tag_name}>after"
        clean, reasoning = extract_and_strip_think_blocks(text)
        assert clean == "beforeafter"
        assert reasoning == "inner"

    @pytest.mark.parametrize("tag_name", THINKING_TAG_NAMES)
    def test_sanitize_text_strips_all_tag_names(self, tag_name: str) -> None:
        text = f"A<{tag_name}>hidden</{tag_name}>B"
        assert sanitize_text(text) == "AB"


class TestSanitizeLlmOutput:
    def test_empty_string(self) -> None:
        assert sanitize_llm_output("") == ""

    def test_normal_text_unchanged(self) -> None:
        s = "Hello 世界 123\nSecond line"
        assert sanitize_llm_output(s) == s

    def test_removes_c0_except_tab_lf_cr(self) -> None:
        # BEL \x07 removed; tab \x09, LF \x0a, CR \x0d kept
        raw = "a\x07b\tc\nd\re"
        assert sanitize_llm_output(raw) == "ab\tc\nd\re"

    def test_removes_c1_control_chars(self) -> None:
        # C1 range includes \x80-\x9F per sanitizer (and DEL \x7f)
        raw = "x\x80\x9fy"
        assert sanitize_llm_output(raw) == "xy"

    def test_removes_model_control_markers(self) -> None:
        raw = "pre<|endoftext|>mid<|im_start|>post"
        assert sanitize_llm_output(raw) == "premidpost"

    def test_removes_fullwidth_pipe_model_tokens(self) -> None:
        raw = "pre<\uff5cassistant\uff5c>mid<\uff5cend\uff5c>post"
        assert sanitize_llm_output(raw) == "premidpost"

    def test_removes_deepseek_subscript_dot_tokens(self) -> None:
        raw = "pre<\uff5cbegin\u2581of\u2581sentence\uff5c>mid<\uff5ctool\u2581calls\uff5c>post"
        assert sanitize_llm_output(raw) == "premidpost"

    def test_removes_unicode_replacement_char(self) -> None:
        raw = "ok\ufffdtail"
        assert sanitize_llm_output(raw) == "oktail"

    def test_mixed_scenario(self) -> None:
        raw = "Hi\x00<|endoftext|>\nok\ufffd\x7f"
        out = sanitize_llm_output(raw)
        assert "\x00" not in out
        assert "<|endoftext|>" not in out
        assert "\ufffd" not in out
        assert "\n" in out
        assert "ok" in out
