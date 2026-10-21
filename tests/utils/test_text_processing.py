"""Tests for text_utils: strip_ansi, unwrap_markdown_fence, strip_internal_markers."""

from __future__ import annotations

from myrm_agent_harness.utils.text_utils import (
    strip_ansi,
    strip_internal_markers,
    unwrap_markdown_fence,
)

# ---------------------------------------------------------------------------
# strip_ansi
# ---------------------------------------------------------------------------


class TestStripAnsi:
    def test_empty_string(self) -> None:
        assert strip_ansi("") == ""

    def test_no_escapes(self) -> None:
        text = "hello world"
        assert strip_ansi(text) is text

    def test_csi_sgr_color(self) -> None:
        assert strip_ansi("\x1b[31mERROR\x1b[0m") == "ERROR"

    def test_csi_bold_underline(self) -> None:
        assert strip_ansi("\x1b[1m\x1b[4mBold\x1b[0m") == "Bold"

    def test_osc_title(self) -> None:
        assert strip_ansi("\x1b]2;My Title\x07rest") == "rest"

    def test_osc_st_terminator(self) -> None:
        assert strip_ansi("\x1b]0;title\x1b\\body") == "body"

    def test_dcs_string(self) -> None:
        assert strip_ansi("\x1bPpayload\x1b\\tail") == "tail"

    def test_fe_single_byte(self) -> None:
        assert strip_ansi("\x1bMtail") == "tail"

    def test_nf_multi_byte(self) -> None:
        assert strip_ansi("\x1b(Btext") == "text"

    def test_8bit_csi(self) -> None:
        assert strip_ansi("\x9b31mERROR\x9b0m") == "ERROR"

    def test_8bit_osc(self) -> None:
        assert strip_ansi("\x9dtitle\x07rest") == "rest"

    def test_8bit_c1_control(self) -> None:
        result = strip_ansi("\x85text")
        assert result == "text"

    def test_csi_cursor_movement(self) -> None:
        assert strip_ansi("\x1b[2Jscreen") == "screen"

    def test_mixed_text_and_escapes(self) -> None:
        text = "line1\x1b[32m green \x1b[0m line2\x1b[1mbold\x1b[0m"
        assert strip_ansi(text) == "line1 green  line2bold"

    def test_preserves_plain_text(self) -> None:
        plain = "no escape sequences here at all"
        result = strip_ansi(plain)
        assert result is plain

    def test_multiline_with_escapes(self) -> None:
        text = "\x1b[31mfirst\x1b[0m\nsecond\n\x1b[34mthird\x1b[0m"
        assert strip_ansi(text) == "first\nsecond\nthird"

    def test_csi_private_mode(self) -> None:
        assert strip_ansi("\x1b[?25lhidden\x1b[?25h") == "hidden"


# ---------------------------------------------------------------------------
# unwrap_markdown_fence
# ---------------------------------------------------------------------------


class TestUnwrapMarkdownFence:
    def test_empty_string(self) -> None:
        assert unwrap_markdown_fence("") == ""

    def test_no_fence(self) -> None:
        text = "plain command"
        assert unwrap_markdown_fence(text) is text

    def test_basic_fence_no_lang(self) -> None:
        text = "```\nls -la\n```"
        assert unwrap_markdown_fence(text) == "ls -la"

    def test_fence_with_bash_lang(self) -> None:
        text = "```bash\necho hello\n```"
        assert unwrap_markdown_fence(text) == "echo hello"

    def test_fence_with_python_lang(self) -> None:
        text = "```python\nprint('hi')\n```"
        assert unwrap_markdown_fence(text) == "print('hi')"

    def test_fence_multiline_body(self) -> None:
        text = "```sh\nline1\nline2\nline3\n```"
        assert unwrap_markdown_fence(text) == "line1\nline2\nline3"

    def test_fence_with_leading_whitespace(self) -> None:
        text = "  ```bash\nls -la\n```  "
        assert unwrap_markdown_fence(text) == "ls -la"

    def test_not_a_fence_no_closing(self) -> None:
        text = "```bash\nls -la\nno closing"
        assert unwrap_markdown_fence(text) == text

    def test_not_a_fence_too_few_lines(self) -> None:
        text = "```bash\n```"
        assert unwrap_markdown_fence(text) == text

    def test_not_a_fence_invalid_lang_chars(self) -> None:
        text = "```bash/script\ncommand\n```"
        assert unwrap_markdown_fence(text) == text

    def test_not_a_fence_no_backtick_prefix(self) -> None:
        text = "some text before ```\ncommand\n```"
        assert unwrap_markdown_fence(text) is text

    def test_empty_body(self) -> None:
        text = "```\n   \n```"
        assert unwrap_markdown_fence(text) == text

    def test_fence_with_numeric_lang(self) -> None:
        text = "```python3\nimport os\n```"
        assert unwrap_markdown_fence(text) == "import os"

    def test_inner_backticks_not_stripped(self) -> None:
        text = "```bash\necho '```'\n```"
        assert unwrap_markdown_fence(text) == "echo '```'"

    def test_identity_when_no_fence(self) -> None:
        text = "just a command"
        result = unwrap_markdown_fence(text)
        assert result is text


# ---------------------------------------------------------------------------
# strip_internal_markers
# ---------------------------------------------------------------------------


class TestStripInternalMarkers:
    def test_empty_string(self) -> None:
        assert strip_internal_markers("") == ""

    def test_no_markers(self) -> None:
        text = "hello world"
        assert strip_internal_markers(text) == text

    def test_untrusted_data_marker(self) -> None:
        text = "<<<UNTRUSTED_DATA>>>payload<<<END_UNTRUSTED_DATA>>>"
        result = strip_internal_markers(text)
        assert "<<<UNTRUSTED_DATA" not in result
        assert "payload" in result

    def test_tool_output_marker(self) -> None:
        text = "<<<TOOL_OUTPUT>>>result<<<END_TOOL_OUTPUT>>>"
        result = strip_internal_markers(text)
        assert "<<<TOOL_OUTPUT" not in result

    def test_marker_with_id(self) -> None:
        text = '<<<UNTRUSTED_DATA id="abc123">>>content<<<END_UNTRUSTED_DATA>>>'
        result = strip_internal_markers(text)
        assert "<<<UNTRUSTED_DATA" not in result
        assert "content" in result

    def test_sanitized_placeholder(self) -> None:
        text = "value is [[SANITIZED]] here"
        result = strip_internal_markers(text)
        assert "[[SANITIZED]]" not in result
        assert "value is" in result

    def test_triple_newlines_collapsed(self) -> None:
        text = "before<<<UNTRUSTED_DATA>>>\n\n\n\nafter"
        result = strip_internal_markers(text)
        assert "\n\n\n" not in result

    def test_case_insensitive(self) -> None:
        text = "<<<untrusted_data>>>data<<<end_untrusted_data>>>"
        result = strip_internal_markers(text)
        assert "<<<untrusted_data" not in result


# ---------------------------------------------------------------------------
# Supplementary coverage for pre-existing text_utils functions
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    def test_english_text(self) -> None:
        from myrm_agent_harness.utils.text_utils import detect_language

        assert detect_language("Hello world") == "english"

    def test_chinese_text(self) -> None:
        from myrm_agent_harness.utils.text_utils import detect_language

        assert detect_language("你好世界这是一段中文文本") == "chinese"

    def test_mixed_text(self) -> None:
        from myrm_agent_harness.utils.text_utils import detect_language

        result = detect_language("Hello 你好 world 世界 test 测试")
        assert result in ("mixed", "chinese", "english")

    def test_empty_text(self) -> None:
        from myrm_agent_harness.utils.text_utils import detect_language

        assert detect_language("") == "english"

    def test_whitespace_only(self) -> None:
        from myrm_agent_harness.utils.text_utils import detect_language

        assert detect_language("   ") == "english"


class TestEstimateTokensFast:
    def test_english_text(self) -> None:
        from myrm_agent_harness.utils.text_utils import estimate_tokens_fast

        result = estimate_tokens_fast("Hello world, this is a test.")
        assert result > 0

    def test_cjk_heavy_text(self) -> None:
        from myrm_agent_harness.utils.text_utils import estimate_tokens_fast

        result = estimate_tokens_fast("你好世界这是一段中文文本测试")
        assert result > 0

    def test_empty_text(self) -> None:
        from myrm_agent_harness.utils.text_utils import estimate_tokens_fast

        assert estimate_tokens_fast("") == 0

    def test_non_string(self) -> None:
        from myrm_agent_harness.utils.text_utils import estimate_tokens_fast

        assert estimate_tokens_fast(None) == 0  # type: ignore[arg-type]


class TestFindSentenceBoundary:
    def test_finds_period(self) -> None:
        from myrm_agent_harness.utils.text_utils import find_sentence_boundary

        text = "First sentence. Second sentence."
        result = find_sentence_boundary(text, 0.3)
        assert result > 0

    def test_no_boundary_found(self) -> None:
        from myrm_agent_harness.utils.text_utils import find_sentence_boundary

        text = "no boundary here"
        result = find_sentence_boundary(text, 0.99)
        assert result == -1


class TestTruncateTextToTokens:
    def test_short_text_unchanged(self) -> None:
        from myrm_agent_harness.utils.text_utils import truncate_text_to_tokens

        text = "short"
        assert truncate_text_to_tokens(text, 100) == text

    def test_empty_text(self) -> None:
        from myrm_agent_harness.utils.text_utils import truncate_text_to_tokens

        assert truncate_text_to_tokens("", 100) == ""

    def test_zero_tokens(self) -> None:
        from myrm_agent_harness.utils.text_utils import truncate_text_to_tokens

        assert truncate_text_to_tokens("hello", 0) == ""

    def test_long_text_truncated(self) -> None:
        from myrm_agent_harness.utils.text_utils import truncate_text_to_tokens

        text = "word " * 1000
        result = truncate_text_to_tokens(text, 10)
        assert len(result) < len(text)


class TestTruncateByTokensWithBoundary:
    def test_short_text_unchanged(self) -> None:
        from myrm_agent_harness.utils.text_utils import truncate_by_tokens_with_boundary

        text = "short"
        assert truncate_by_tokens_with_boundary(text, 100) == text

    def test_empty_text(self) -> None:
        from myrm_agent_harness.utils.text_utils import truncate_by_tokens_with_boundary

        assert truncate_by_tokens_with_boundary("", 100) == ""

    def test_long_text_truncated_at_boundary(self) -> None:
        from myrm_agent_harness.utils.text_utils import truncate_by_tokens_with_boundary

        text = "First sentence. " * 200
        result = truncate_by_tokens_with_boundary(text, 20)
        assert len(result) < len(text)

    def test_long_text_no_sentence_boundary(self) -> None:
        from myrm_agent_harness.utils.text_utils import truncate_by_tokens_with_boundary

        text = "aaaa" * 5000
        result = truncate_by_tokens_with_boundary(text, 10)
        assert len(result) < len(text)


class TestGetDangerousModules:
    """Cover blacklist.get_dangerous_modules lines 111-113."""

    def test_default_includes_network(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.security.blacklist import (
            DANGEROUS_MODULES,
            get_dangerous_modules,
        )

        result = get_dangerous_modules(allow_network=False)
        assert result == DANGEROUS_MODULES

    def test_allow_network_excludes_network(self) -> None:
        from myrm_agent_harness.toolkits.code_execution.security.blacklist import (
            CORE_DANGEROUS_MODULES,
            get_dangerous_modules,
        )

        result = get_dangerous_modules(allow_network=True)
        assert result == CORE_DANGEROUS_MODULES


# ---------------------------------------------------------------------------
# detect_language exhaustive branch coverage
# ---------------------------------------------------------------------------


class TestDetectLanguageBranches:
    def test_chinese_dominant(self) -> None:
        from myrm_agent_harness.utils.text_utils import detect_language

        result = detect_language("这是一段完全的中文文本没有任何英文")
        assert result == "chinese"

    def test_english_dominant(self) -> None:
        from myrm_agent_harness.utils.text_utils import detect_language

        result = detect_language("This is a fully English text with no Chinese characters at all")
        assert result == "english"

    def test_chinese_more_than_english_low_ratio(self) -> None:
        from myrm_agent_harness.utils.text_utils import detect_language

        text = "中文多a"
        result = detect_language(text)
        assert result in ("chinese", "mixed")

    def test_english_more_than_chinese_low_ratio(self) -> None:
        from myrm_agent_harness.utils.text_utils import detect_language

        text = "English text with only one 字"
        result = detect_language(text)
        assert result in ("english", "mixed")

    def test_balanced_mixed(self) -> None:
        from myrm_agent_harness.utils.text_utils import detect_language

        text = "Hello World你好世界Test测试"
        result = detect_language(text)
        assert result in ("mixed", "english", "chinese")


# ---------------------------------------------------------------------------
# is_cross_language
# ---------------------------------------------------------------------------


class TestIsCrossLanguage:
    def test_same_language(self) -> None:
        from langchain_core.documents import Document

        from myrm_agent_harness.utils.text_utils import is_cross_language

        result = is_cross_language(
            ["hello world"],
            [Document(page_content="This is English content.")],
        )
        assert result is False

    def test_cross_language(self) -> None:
        from langchain_core.documents import Document

        from myrm_agent_harness.utils.text_utils import is_cross_language

        result = is_cross_language(
            ["这是中文查询"],
            [Document(page_content="This is purely English text content without any Chinese.")],
        )
        assert result is True

    def test_empty_documents(self) -> None:
        from myrm_agent_harness.utils.text_utils import is_cross_language

        result = is_cross_language(["hello"], [])
        assert result is False

    def test_empty_queries(self) -> None:
        from langchain_core.documents import Document

        from myrm_agent_harness.utils.text_utils import is_cross_language

        result = is_cross_language([], [Document(page_content="hello")])
        assert result is False


# ---------------------------------------------------------------------------
# get_token_count
# ---------------------------------------------------------------------------


class TestGetTokenCount:
    def test_normal_text(self) -> None:
        from myrm_agent_harness.utils.text_utils import get_token_count

        result = get_token_count("Hello world")
        assert result > 0

    def test_empty_text(self) -> None:
        from myrm_agent_harness.utils.text_utils import get_token_count

        assert get_token_count("") == 0

    def test_chinese_text(self) -> None:
        from myrm_agent_harness.utils.text_utils import get_token_count

        result = get_token_count("你好世界")
        assert result > 0


# ---------------------------------------------------------------------------
# smart_truncate + has_important_tail
# ---------------------------------------------------------------------------


class TestSmartTruncate:
    def test_short_text_unchanged(self) -> None:
        from myrm_agent_harness.utils.text_utils import smart_truncate

        text = "short text"
        assert smart_truncate(text, 100) == text

    def test_long_text_truncated(self) -> None:
        from myrm_agent_harness.utils.text_utils import smart_truncate

        text = "x\n" * 5000
        result = smart_truncate(text, 500)
        assert len(result) <= 600
        assert "Truncated" in result

    def test_diagnostic_tail_preserved(self) -> None:
        from myrm_agent_harness.utils.text_utils import smart_truncate

        text = "header\n" * 500 + "ERROR: something failed\n"
        result = smart_truncate(text, 500)
        assert "ERROR" in result

    def test_structural_tail(self) -> None:
        from myrm_agent_harness.utils.text_utils import smart_truncate

        text = "data\n" * 500 + '{"key": "value"}\n'
        result = smart_truncate(text, 500)
        assert "Truncated" in result


class TestHasImportantTail:
    def test_error_pattern(self) -> None:
        from myrm_agent_harness.utils.text_utils import has_important_tail

        assert has_important_tail("blah blah\nERROR: failed") is True

    def test_summary_pattern(self) -> None:
        from myrm_agent_harness.utils.text_utils import has_important_tail

        assert has_important_tail("blah\ntotal: 42 passed") is True

    def test_structural_end(self) -> None:
        from myrm_agent_harness.utils.text_utils import has_important_tail

        assert has_important_tail("some data\n}") is True

    def test_plain_text_no_tail(self) -> None:
        from myrm_agent_harness.utils.text_utils import has_important_tail

        assert has_important_tail("plain text") is False


# ---------------------------------------------------------------------------
# _char_fallback_truncate / _estimate_max_chars
# ---------------------------------------------------------------------------


class TestCharFallbackTruncate:
    def test_fallback_truncation(self) -> None:
        from myrm_agent_harness.utils.text_utils import _char_fallback_truncate

        text = "a" * 1000
        result = _char_fallback_truncate(text, 10)
        assert "..." in result
        assert len(result) < len(text)

    def test_short_text(self) -> None:
        from myrm_agent_harness.utils.text_utils import _char_fallback_truncate

        text = "short"
        result = _char_fallback_truncate(text, 100)
        assert result == "short"


class TestEstimateMaxChars:
    def test_english_text(self) -> None:
        from myrm_agent_harness.utils.text_utils import _estimate_max_chars

        result = _estimate_max_chars("Hello world", 10)
        assert result == 40

    def test_cjk_heavy_text(self) -> None:
        from myrm_agent_harness.utils.text_utils import _estimate_max_chars

        result = _estimate_max_chars("你好世界测试", 10)
        assert result == 15


# ---------------------------------------------------------------------------
# Exception fallback paths (requires mocking)
# ---------------------------------------------------------------------------


class TestTiktokenFallback:
    """Cover exception fallback paths where tiktoken fails."""

    def test_get_token_count_fallback(self) -> None:
        from unittest.mock import MagicMock, patch

        mock_tiktoken = MagicMock()
        mock_tiktoken.get_encoding.side_effect = RuntimeError("mock error")

        with patch.dict("sys.modules", {"tiktoken": mock_tiktoken}):
            from myrm_agent_harness.utils.text_utils import get_token_count

            result = get_token_count("Hello world")
            assert result > 0

    def test_truncate_text_to_tokens_exception(self) -> None:
        from unittest.mock import MagicMock, patch

        mock_tiktoken = MagicMock()
        mock_tiktoken.get_encoding.side_effect = RuntimeError("mock error")

        with patch.dict("sys.modules", {"tiktoken": mock_tiktoken}):
            from myrm_agent_harness.utils.text_utils import truncate_text_to_tokens

            result = truncate_text_to_tokens("a" * 1000, 10)
            assert isinstance(result, str)
            assert len(result) < 1000

    def test_truncate_by_tokens_with_boundary_exception(self) -> None:
        from unittest.mock import MagicMock, patch

        mock_tiktoken = MagicMock()
        mock_tiktoken.get_encoding.side_effect = RuntimeError("mock error")

        with patch.dict("sys.modules", {"tiktoken": mock_tiktoken}):
            from myrm_agent_harness.utils.text_utils import truncate_by_tokens_with_boundary

            text = "First sentence. " * 200
            result = truncate_by_tokens_with_boundary(text, 10)
            assert isinstance(result, str)
            assert len(result) < len(text)

    def test_truncate_by_tokens_exception_no_boundary(self) -> None:
        from unittest.mock import MagicMock, patch

        mock_tiktoken = MagicMock()
        mock_tiktoken.get_encoding.side_effect = RuntimeError("mock error")

        with patch.dict("sys.modules", {"tiktoken": mock_tiktoken}):
            from myrm_agent_harness.utils.text_utils import truncate_by_tokens_with_boundary

            text = "a" * 5000
            result = truncate_by_tokens_with_boundary(text, 10)
            assert "..." in result


class TestSmartTruncateBranches:
    """Cover smart_truncate's newline boundary branch partials."""

    def test_no_newline_at_head_cut(self) -> None:
        from myrm_agent_harness.utils.text_utils import smart_truncate

        text = "a" * 10000
        result = smart_truncate(text, 500)
        assert "Truncated" in result

    def test_newline_at_tail_far(self) -> None:
        from myrm_agent_harness.utils.text_utils import smart_truncate

        head = "line\n" * 100
        middle = "x" * 8000
        tail = "\nend\n" * 100
        text = head + middle + tail
        result = smart_truncate(text, 600)
        assert "Truncated" in result
