"""Tests for empty tool output normalization in tool_interceptor_middleware."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.middlewares._tool_helpers import extract_text_content as _extract_text_content


class TestExtractTextContent:
    def test_normal_string(self) -> None:
        assert _extract_text_content("hello world") == "hello world"

    def test_empty_string(self) -> None:
        assert _extract_text_content("") == ""

    def test_whitespace_only(self) -> None:
        assert _extract_text_content("   ") == "   "

    def test_list_with_text_blocks(self) -> None:
        content = [
            {"type": "text", "text": "first"},
            {"type": "text", "text": " second"},
        ]
        assert _extract_text_content(content) == "first second"

    def test_list_with_non_text_blocks(self) -> None:
        content = [
            {"type": "image", "url": "http://example.com"},
            {"type": "text", "text": "only text"},
        ]
        assert _extract_text_content(content) == "only text"

    def test_empty_list(self) -> None:
        assert _extract_text_content([]) == ""


class TestEmptyOutputNormalization:
    """Verify that the normalization logic in tool_interceptor_middleware
    would replace empty/whitespace-only tool output with '(no output)'.

    The actual replacement happens inside the async middleware pipeline,
    so we test the condition logic directly.
    """

    @pytest.mark.parametrize(
        "content,should_normalize",
        [
            ("", True),
            ("   ", True),
            ("\n\t", True),
            ("(no output)", False),
            ("some result", False),
            ("0", False),
        ],
    )
    def test_normalization_condition(self, content: str, should_normalize: bool) -> None:
        result_text = _extract_text_content(content)
        needs_normalization = not result_text.strip()
        assert needs_normalization == should_normalize, (
            f"content={content!r}: expected needs_normalization={should_normalize}, got {needs_normalization}"
        )
