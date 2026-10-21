"""Tests for surrogate character sanitization in text_sanitizer."""

from myrm_agent_harness.utils.text_sanitizer import sanitize_llm_output, sanitize_text


class TestSurrogateCharacterSanitization:
    def test_removes_unpaired_high_surrogate(self) -> None:
        """Test removal of unpaired high surrogate (U+D800-U+DBFF)."""
        text = "Hello\ud800World"
        assert sanitize_text(text) == "HelloWorld"

    def test_removes_unpaired_low_surrogate(self) -> None:
        """Test removal of unpaired low surrogate (U+DC00-U+DFFF)."""
        text = "Hello\udc00World"
        assert sanitize_text(text) == "HelloWorld"

    def test_removes_multiple_surrogates(self) -> None:
        """Test removal of multiple unpaired surrogates."""
        text = "A\ud800B\udc00C\udbffD"
        assert sanitize_text(text) == "ABCD"

    def test_preserves_valid_unicode(self) -> None:
        """Test that valid Unicode characters are preserved."""
        text = "Hello 世界  \u4e2d\u6587"
        assert sanitize_text(text) == text

    def test_surrogate_with_other_control_chars(self) -> None:
        """Test surrogate removal combined with other control chars."""
        raw = "A\ud800\x00B\ufffdC<|endoftext|>D\udc00E"
        expected = "ABCDE"
        assert sanitize_text(raw) == expected

    def test_sanitize_llm_output_uses_sanitize_text(self) -> None:
        """Test that sanitize_llm_output delegates to sanitize_text."""
        text = "Hello\ud800World"
        assert sanitize_llm_output(text) == sanitize_text(text)
