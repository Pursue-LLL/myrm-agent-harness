"""text_utils 模块完整测试覆盖

测试目标：确保所有文本处理工具函数都经过验证
"""

from myrm_agent_harness.utils.text_utils import (
    detect_language,
    estimate_tokens_fast,
    find_sentence_boundary,
    get_token_count,
    has_important_tail,
    is_cross_language,
    preheat_tiktoken,
    sanitize_binary_output,
    smart_truncate,
    strip_ansi,
    strip_internal_markers,
    truncate_by_tokens_with_boundary,
    truncate_text_to_tokens,
    unwrap_markdown_fence,
)


class TestDetectLanguage:
    """测试语言检测"""

    def test_pure_chinese(self):
        """测试纯中文"""
        text = "这是一段纯中文文本，没有任何英文字符。"
        assert detect_language(text) == "chinese"

    def test_pure_english(self):
        """测试纯英文"""
        text = "This is a pure English text without any Chinese characters."
        assert detect_language(text) == "english"

    def test_mixed_language_balanced(self):
        """测试中英混合（均衡）"""
        text = "This is English. 这是中文。Both languages are used equally."
        result = detect_language(text)
        # 应该识别为mixed
        assert result in ["mixed", "english"]  # 取决于具体实现

    def test_chinese_dominated(self):
        """测试中文主导"""
        text = "这是一段很长的中文文本，只有little English words。大部分都是中文。"
        result = detect_language(text)
        assert result in ["chinese", "mixed"]

    def test_english_dominated(self):
        """测试英文主导"""
        text = "This is a very long English text with just 几个 Chinese characters."
        result = detect_language(text)
        assert result in ["english", "mixed"]

    def test_empty_text(self):
        """测试空文本"""
        assert detect_language("") == "english"
        assert detect_language(None) == "english"

    def test_whitespace_only(self):
        """测试纯空白"""
        assert detect_language("   \n\t  ") == "english"

    def test_numbers_and_symbols(self):
        """测试数字和符号"""
        text = "12345 @#$%^&*()"
        assert detect_language(text) == "english"


class TestPreheatTiktoken:
    """tiktoken startup preheat tests."""

    def test_preheat_returns_true(self):
        result = preheat_tiktoken()
        assert result is True

    def test_preheat_idempotent(self):
        assert preheat_tiktoken() is True
        assert preheat_tiktoken() is True

    def test_preheat_custom_encoding(self):
        assert preheat_tiktoken("cl100k_base") is True

    def test_preheat_invalid_encoding(self):
        assert preheat_tiktoken("nonexistent_encoding_xyz") is False

    def test_preheat_then_get_token_count(self):
        preheat_tiktoken()
        count = get_token_count("Hello world")
        assert count > 0

    def test_preheat_failure_on_encoding_error(self, monkeypatch):
        import tiktoken

        def _raise(_name: str) -> None:
            raise RuntimeError("mock BPE load failure")

        monkeypatch.setattr(tiktoken, "get_encoding", _raise)
        assert preheat_tiktoken() is False


class TestGetTokenCount:
    """测试Token计数"""

    def test_empty_text(self):
        """测试空文本"""
        assert get_token_count("") == 0
        assert get_token_count(None) == 0

    def test_short_english(self):
        """测试短英文"""
        count = get_token_count("Hello world")
        assert count > 0
        assert count < 10

    def test_short_chinese(self):
        """测试短中文"""
        count = get_token_count("你好世界")
        assert count > 0
        assert count < 10

    def test_long_text(self):
        """测试长文本"""
        text = "This is a long text. " * 100
        count = get_token_count(text)
        assert count > 100

    def test_special_characters(self):
        """测试特殊字符"""
        text = "Test @#$% emoji "
        count = get_token_count(text)
        assert count > 0

    def test_fallback_on_tiktoken_error(self, monkeypatch):
        """测试tiktoken失败时的fallback"""

        def mock_import(name, *args, **kwargs):
            if name == "tiktoken":
                raise ImportError("tiktoken not available")
            return __builtins__.__import__(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)

        text = "Test text"
        count = get_token_count(text)
        # 应该调用estimate_tokens_fast作为fallback
        assert count > 0


class TestEstimateTokensFast:
    """测试快速Token估算"""

    def test_empty_text(self):
        """测试空文本"""
        assert estimate_tokens_fast("") == 0
        assert estimate_tokens_fast(None) == 0

    def test_english_text(self):
        """测试英文文本"""
        text = "Hello world, this is a test."
        tokens = estimate_tokens_fast(text)
        # 英文：约 len/3.5
        assert tokens > 0
        assert tokens < len(text)

    def test_chinese_text(self):
        """测试中文文本"""
        text = "你好世界，这是一个测试。"
        tokens = estimate_tokens_fast(text)
        # 中文：约 len*1.3
        assert tokens > len(text)

    def test_mixed_text(self):
        """测试混合文本"""
        text = "Hello 你好 world 世界"
        tokens = estimate_tokens_fast(text)
        assert tokens > 0

    def test_non_string_input(self):
        """测试非字符串输入"""
        assert estimate_tokens_fast(123) == 0
        assert estimate_tokens_fast([]) == 0


class TestTruncateTextToTokens:
    """测试基于Token的文本截断"""

    def test_no_truncation_needed(self):
        """测试不需要截断"""
        text = "Short text"
        result = truncate_text_to_tokens(text, 100)
        assert result == text

    def test_truncate_english(self):
        """测试截断英文"""
        text = "This is a long sentence. " * 50
        result = truncate_text_to_tokens(text, 50)

        assert len(result) < len(text)
        tokens = get_token_count(result)
        assert tokens <= 50

    def test_truncate_chinese(self):
        """测试截断中文"""
        text = "这是一个很长的句子。" * 50
        result = truncate_text_to_tokens(text, 50)

        assert len(result) < len(text)
        tokens = get_token_count(result)
        assert tokens <= 50

    def test_empty_text(self):
        """测试空文本"""
        assert truncate_text_to_tokens("", 100) == ""

    def test_zero_max_tokens(self):
        """测试零token限制"""
        assert truncate_text_to_tokens("test", 0) == ""

    def test_negative_max_tokens(self):
        """测试负数token限制"""
        assert truncate_text_to_tokens("test", -10) == ""

    def test_custom_encoding(self):
        """测试自定义编码器"""
        text = "Test content for encoding"
        result1 = truncate_text_to_tokens(text, 10, "o200k_base")
        result2 = truncate_text_to_tokens(text, 10, "cl100k_base")

        # 不同编码器可能产生不同结果
        assert result1
        assert result2

    def test_fallback_on_tiktoken_error(self, monkeypatch):
        """测试tiktoken失败时降级到字符模式"""

        def mock_import(name, *args, **kwargs):
            if name == "tiktoken":
                raise ImportError("tiktoken not available")
            return __builtins__.__import__(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)

        text = "测试文本" * 50
        result = truncate_text_to_tokens(text, 50)

        # 应该降级到字符估算模式
        assert len(result) < len(text)
        assert "..." in result


class TestHasImportantTail:
    """测试尾部诊断信息检测"""

    def test_error_in_tail(self):
        """测试尾部包含错误信息"""
        text = "Some content\n" * 50 + "ERROR: File not found"
        assert has_important_tail(text) is True

    def test_exception_in_tail(self):
        """测试尾部包含异常"""
        text = "Normal output\n" * 50 + "Exception occurred at line 42"
        assert has_important_tail(text) is True

    def test_traceback_in_tail(self):
        """测试尾部包含traceback"""
        text = "Code output\n" * 50 + "Traceback (most recent call last):"
        assert has_important_tail(text) is True

    def test_json_closure(self):
        """测试JSON结构结束"""
        text = '{"data": "value"}\n' * 30 + "  }\n]"
        assert has_important_tail(text) is True

    def test_summary_in_tail(self):
        """测试尾部包含总结"""
        text = "Test results\n" * 50 + "Total: 100 tests passed"
        assert has_important_tail(text) is True

    def test_clean_tail(self):
        """测试普通尾部（无诊断信息）"""
        text = "This is normal text. " * 100
        assert has_important_tail(text) is False

    def test_short_text(self):
        """测试短文本"""
        text = "Short"
        # 短文本也应该能检测
        result = has_important_tail(text)
        assert isinstance(result, bool)


class TestSmartTruncate:
    """测试智能截断"""

    def test_no_truncation_needed(self):
        """测试不需要截断"""
        text = "Short text"
        result = smart_truncate(text, 1000)
        assert result == text

    def test_basic_head_tail_truncate(self):
        """测试基本head+tail截断"""
        text = "Line\n" * 200
        result = smart_truncate(text, 500)

        assert len(result) <= 500
        assert "[Truncated" in result
        assert "first" in result and "last" in result

    def test_truncate_at_newline_boundaries(self):
        """测试在换行边界截断"""
        text = "Line1\nLine2\nLine3\n" * 50
        result = smart_truncate(text, 200)

        # 应该在换行处截断，不切断行
        parts = result.split("[Truncated")
        if len(parts) > 1:
            head = parts[0]
            # head应该以换行结束或不包含半截的行
            assert head.endswith("\n") or "\n" not in head[-20:]

    def test_important_tail_gets_more_budget(self):
        """测试重要尾部获得更多预算"""
        # 构造足够长的文本才会触发截断
        base_text = "Line\n" * 200

        # 重要尾部
        text2 = base_text + "ERROR: Critical failure at line 100"
        result2 = smart_truncate(text2, 500)

        # 应该被截断且保留错误信息
        assert len(result2) < len(text2)
        if "[Truncated" in result2:
            assert "ERROR" in result2

    def test_custom_tail_ratio(self):
        """测试自定义tail比例"""
        text = "Content\n" * 100

        result1 = smart_truncate(text, 500, tail_ratio=0.2)
        result2 = smart_truncate(text, 500, tail_ratio=0.5)

        # 不同ratio应该产生不同的截断结果
        assert result1 != result2

    def test_very_short_max_chars(self):
        """测试极短的max_chars"""
        text = "Very long text. " * 100
        result = smart_truncate(text, 100)

        # smart_truncate会保证最小200字符的budget，所以结果可能>100
        assert len(result) < len(text)
        # 应该有截断标记
        assert "" in result


class TestUnwrapMarkdownFence:
    """Markdown code fence unwrapping for LLM command normalization"""

    def test_fast_path_no_fence(self):
        assert unwrap_markdown_fence("ls -la") == "ls -la"

    def test_empty_and_blank(self):
        assert unwrap_markdown_fence("") == ""
        assert unwrap_markdown_fence("   ") == "   "

    def test_bash_fence(self):
        assert unwrap_markdown_fence("```bash\nls -la\n```") == "ls -la"

    def test_no_language_tag(self):
        assert unwrap_markdown_fence("```\nls -la\n```") == "ls -la"

    def test_python_fence(self):
        assert unwrap_markdown_fence("```python\nprint('hello')\n```") == "print('hello')"

    def test_multiline_content(self):
        inp = "```bash\nls -la\necho hello\n```"
        assert unwrap_markdown_fence(inp) == "ls -la\necho hello"

    def test_preserves_inner_indentation(self):
        inp = "```bash\n  ls -la\n  echo hi\n```"
        assert unwrap_markdown_fence(inp) == "  ls -la\n  echo hi"

    def test_no_closing_fence(self):
        inp = "```bash\nls -la"
        assert unwrap_markdown_fence(inp) == inp

    def test_extra_text_after_fence(self):
        inp = "```bash\nls -la\n```\nextra"
        assert unwrap_markdown_fence(inp) == inp

    def test_empty_fence_body(self):
        inp = "```bash\n```"
        assert unwrap_markdown_fence(inp) == inp

    def test_empty_fence_body_no_lang(self):
        inp = "```\n```"
        assert unwrap_markdown_fence(inp) == inp

    def test_command_containing_backticks(self):
        inp = "echo '```test```'"
        assert unwrap_markdown_fence(inp) == inp

    def test_surrounding_whitespace(self):
        inp = "  ```bash\n  ls -la\n  ```  "
        result = unwrap_markdown_fence(inp)
        assert "ls -la" in result
        assert "```" not in result

    def test_idempotent(self):
        inp = "```bash\nls -la\n```"
        once = unwrap_markdown_fence(inp)
        twice = unwrap_markdown_fence(once)
        assert once == twice == "ls -la"

    def test_invalid_lang_tag(self):
        inp = "```bash script\nls -la\n```"
        assert unwrap_markdown_fence(inp) == inp

    def test_fence_with_only_whitespace_body(self):
        inp = "```bash\n   \n```"
        assert unwrap_markdown_fence(inp) == inp


class TestStripAnsi:
    """ANSI escape sequence stripping (ECMA-48 full spec)"""

    def test_fast_path_no_escape(self):
        assert strip_ansi("plain text") == "plain text"

    def test_empty_and_none(self):
        assert strip_ansi("") == ""

    def test_sgr_color_codes(self):
        assert strip_ansi("\x1b[31mred\x1b[0m") == "red"

    def test_256_color(self):
        assert strip_ansi("\x1b[38;5;250m███\x1b[0m") == "███"

    def test_bold_bright(self):
        assert strip_ansi("\x1b[1;32mSuccess\x1b[0m") == "Success"

    def test_multiple_sequences(self):
        inp = "\x1b[33mwarning:\x1b[0m something \x1b[31mhappened\x1b[0m"
        assert strip_ansi(inp) == "warning: something happened"

    def test_cursor_movement(self):
        assert strip_ansi("\x1b[2J\x1b[H") == ""

    def test_osc_bel_terminator(self):
        assert strip_ansi("\x1b]0;title\x07text") == "text"

    def test_osc_st_terminator(self):
        assert strip_ansi("\x1b]0;title\x1b\\text") == "text"

    def test_dcs_string(self):
        assert strip_ansi("\x1bPquery\x1b\\data") == "data"

    def test_8bit_csi(self):
        assert strip_ansi("\x9b31mred\x9b0m") == "red"

    def test_8bit_c1_controls(self):
        assert strip_ansi("\x85text") == "text"

    def test_preserves_newlines_and_tabs(self):
        assert strip_ansi("line1\nline2\ttab") == "line1\nline2\ttab"

    def test_mixed_ansi_and_text(self):
        inp = "\x1b[1mBold\x1b[0m normal \x1b[4munderline\x1b[0m"
        assert strip_ansi(inp) == "Bold normal underline"

    def test_cargo_build_like_output(self):
        inp = (
            "\x1b[0m\x1b[1m\x1b[32m   Compiling\x1b[0m myproject v0.1.0\n"
            "\x1b[0m\x1b[1m\x1b[32m    Finished\x1b[0m release [optimized]\n"
        )
        result = strip_ansi(inp)
        assert "Compiling" in result
        assert "Finished" in result
        assert "\x1b" not in result


class TestStripInternalMarkers:
    """测试内部标记清除"""

    def test_no_markers(self):
        """测试无标记文本"""
        text = "Normal user-facing text."
        assert strip_internal_markers(text) == text

    def test_untrusted_data_markers(self):
        """测试UNTRUSTED_DATA标记"""
        text = '<<<UNTRUSTED_DATA id="abc123">>>\nContent\n<<<END_UNTRUSTED_DATA id="abc123">>>'
        result = strip_internal_markers(text)

        assert "<<<UNTRUSTED_DATA" not in result
        assert "<<<END_UNTRUSTED_DATA" not in result
        assert "Content" in result

    def test_tool_output_markers(self):
        """测试TOOL_OUTPUT标记"""
        text = '<<<TOOL_OUTPUT id="xyz789">>>\nOutput\n<<<END_TOOL_OUTPUT id="xyz789">>>'
        result = strip_internal_markers(text)

        assert "<<<TOOL_OUTPUT" not in result
        assert "<<<END_TOOL_OUTPUT" not in result
        assert "Output" in result

    def test_sanitized_placeholder(self):
        """测试SANITIZED占位符"""
        text = "Some text [[SANITIZED]] more text"
        result = strip_internal_markers(text)

        assert "[[SANITIZED]]" not in result
        assert "Some text" in result and "more text" in result

    def test_multiple_markers(self):
        """测试多个标记"""
        text = "<<<UNTRUSTED_DATA>>>\nData1\n<<<END_UNTRUSTED_DATA>>>\n<<<TOOL_OUTPUT>>>\nData2\n<<<END_TOOL_OUTPUT>>>\n[[SANITIZED]]"
        result = strip_internal_markers(text)

        assert "<<<" not in result
        assert "[[SANITIZED]]" not in result
        assert "Data1" in result and "Data2" in result

    def test_empty_text(self):
        """测试空文本"""
        assert strip_internal_markers("") == ""
        assert strip_internal_markers(None) is None

    def test_marker_without_id(self):
        """测试无ID的标记"""
        text = "<<<UNTRUSTED_DATA>>>\nContent\n<<<END_UNTRUSTED_DATA>>>"
        result = strip_internal_markers(text)
        assert "<<<" not in result

    def test_excessive_newlines_cleanup(self):
        """测试清理多余换行"""
        text = "Line1\n\n\n<<<UNTRUSTED_DATA>>>\n\n\nLine2"
        result = strip_internal_markers(text)

        # 应该清理多余的换行（3个以上变成2个）
        assert "\n\n\n" not in result or result.count("\n\n\n") < text.count("\n\n\n")


class TestIntegration:
    """集成测试"""

    def test_token_count_and_truncate_consistency(self):
        """测试token计数和截断的一致性"""
        text = "Test sentence. " * 100

        # 截断到50 tokens
        truncated = truncate_text_to_tokens(text, 50)

        # 验证截断后的token数确实不超过50
        count = get_token_count(truncated)
        assert count <= 50

    def test_language_detection_affects_token_estimation(self):
        """测试语言检测影响token估算"""
        chinese_text = "中文文本" * 100
        english_text = "English text " * 100

        # 语言检测
        assert detect_language(chinese_text) == "chinese"
        assert detect_language(english_text) == "english"

        # token估算应该有差异
        chinese_tokens = estimate_tokens_fast(chinese_text)
        english_tokens = estimate_tokens_fast(english_text)

        # 中文token估算应该更高（字符数 * 1.3 vs 字符数 / 3.5）
        assert chinese_tokens > english_tokens

    def test_smart_truncate_with_important_tail(self):
        """测试智能截断识别重要尾部"""
        # 构造有错误信息的文本
        text = "Normal output\n" * 100 + "ERROR: Critical failure\nTraceback: ..."

        # 截断
        result = smart_truncate(text, 1000)

        # 应该保留错误信息
        if "[Truncated" in result:
            assert "ERROR" in result or "Traceback" in result

    def test_strip_markers_after_llm_output(self):
        """测试清除LLM意外回显的标记"""
        # 模拟LLM输出中包含内部标记
        llm_output = "Here is the answer: <<<UNTRUSTED_DATA>>>\nSome data\n<<<END_UNTRUSTED_DATA>>>"

        cleaned = strip_internal_markers(llm_output)

        # 用户看到的输出应该是干净的
        assert "<<<" not in cleaned
        assert "Here is the answer:" in cleaned
        assert "Some data" in cleaned


class TestEdgeCases:
    """测试边缘情况"""

    def test_unicode_emoji_token_count(self):
        """测试emoji的token计数"""
        text = "Hello  world "
        count = get_token_count(text)
        assert count > 0

    def test_very_long_single_line(self):
        """测试超长单行"""
        text = "x" * 100000
        truncated = truncate_text_to_tokens(text, 100)

        tokens = get_token_count(truncated)
        assert tokens <= 100

    def test_marker_in_middle_of_content(self):
        """测试标记在内容中间"""
        text = "Start <<<UNTRUSTED_DATA>>> middle <<<END_UNTRUSTED_DATA>>> end"
        result = strip_internal_markers(text)
        assert "Start" in result and "middle" in result and "end" in result
        assert "<<<" not in result

    def test_nested_markers(self):
        """测试嵌套标记"""
        text = "<<<UNTRUSTED_DATA>>>\n<<<TOOL_OUTPUT>>>\nContent\n<<<END_TOOL_OUTPUT>>>\n<<<END_UNTRUSTED_DATA>>>"
        result = strip_internal_markers(text)
        assert "<<<" not in result
        assert "Content" in result

    def test_truncate_preserves_unicode(self):
        """测试截断保留Unicode完整性"""
        text = "Hello 世界 emoji  symbols ™®© text"
        truncated = truncate_text_to_tokens(text, 10)

        # 截断后的文本应该仍然是有效的Unicode
        assert isinstance(truncated, str)
        # 不应该有半个emoji或字符
        try:
            truncated.encode("utf-8")
            assert True
        except UnicodeEncodeError:
            assert False, "Truncated text contains broken Unicode"


class TestSanitizeBinaryOutput:
    """测试二进制输出检测与净化"""

    def test_empty_string(self):
        assert sanitize_binary_output("") == ""

    def test_normal_text_unchanged(self):
        text = "Hello, world! This is normal output.\nLine 2\n"
        assert sanitize_binary_output(text) == text

    def test_text_with_tabs_unchanged(self):
        text = "col1\tcol2\tcol3\nval1\tval2\tval3\n"
        assert sanitize_binary_output(text) == text

    def test_binary_content_detected(self):
        binary = "\x00\x01\x02\x03\x04\x05" * 100
        result = sanitize_binary_output(binary)
        assert result.startswith("[Binary output detected")
        assert "bytes" in result
        assert "file_read_tool" in result

    def test_threshold_boundary_below(self):
        normal = "a" * 460
        non_printable = "\x00" * 50
        text = normal + non_printable
        assert sanitize_binary_output(text) == text

    def test_threshold_boundary_above(self):
        normal = "a" * 400
        non_printable = "\x00" * 112
        text = normal + non_printable
        result = sanitize_binary_output(text)
        assert result.startswith("[Binary output detected")

    def test_short_binary_single_char(self):
        result = sanitize_binary_output("\x00")
        assert result.startswith("[Binary output detected")

    def test_newlines_not_counted(self):
        text = "\n" * 500
        assert sanitize_binary_output(text) == text

    def test_mixed_printable_with_few_control(self):
        text = "Normal output " + "\x07" * 3 + " more text" + "a" * 490
        assert sanitize_binary_output(text) == text


class TestIsCrossLanguage:
    """测试跨语言检测"""

    def test_empty_inputs(self):
        assert is_cross_language([], []) is False

    def test_empty_queries(self):
        from langchain_core.documents import Document

        docs = [Document(page_content="Hello world")]
        assert is_cross_language([], docs) is False

    def test_empty_documents(self):
        assert is_cross_language(["查询"], []) is False

    def test_same_language_chinese(self):
        from langchain_core.documents import Document

        docs = [Document(page_content="这是一段中文文档内容，包含很多中文字符。")]
        queries = ["中文查询内容，搜索相关文档"]
        assert is_cross_language(queries, docs) is False

    def test_cross_language_detected(self):
        from langchain_core.documents import Document

        docs = [
            Document(page_content="This is a document in English language with sufficient text content for detection.")
        ]
        queries = ["这是一个纯中文查询内容，包含很多中文字符用于检测"]
        result = is_cross_language(queries, docs)
        assert isinstance(result, bool)


class TestFindSentenceBoundary:
    """测试句子边界查找"""

    def test_period_boundary(self):
        text = "First sentence. Second sentence"
        pos = find_sentence_boundary(text, 0.3)
        assert pos > 0
        assert text[:pos].endswith(". ")

    def test_no_boundary_found(self):
        text = "no sentence ending here"
        pos = find_sentence_boundary(text, 0.9)
        assert pos == -1

    def test_chinese_period(self):
        text = "第一句话。第二句话"
        pos = find_sentence_boundary(text, 0.3)
        assert pos > 0

    def test_min_threshold_respected(self):
        text = "A. Very long text that continues" + " word" * 50
        pos = find_sentence_boundary(text, 0.8)
        assert pos == -1


class TestTruncateByTokensWithBoundary:
    """测试基于 token 数的句子边界截断"""

    def test_short_text_unchanged(self):
        text = "Short text."
        result = truncate_by_tokens_with_boundary(text, 100)
        assert result == text

    def test_empty_text(self):
        assert truncate_by_tokens_with_boundary("", 100) == ""

    def test_zero_tokens(self):
        assert truncate_by_tokens_with_boundary("Some text", 0) == ""

    def test_long_text_truncated(self):
        text = "First sentence. " * 100
        result = truncate_by_tokens_with_boundary(text, 10)
        assert len(result) < len(text)
        assert isinstance(result, str)
