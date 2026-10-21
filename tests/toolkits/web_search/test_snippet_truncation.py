"""句子边界查找和字符截断逻辑测试

验证 find_sentence_boundary 的句子边界查找功能。
"""

from myrm_agent_harness.utils.text_utils import find_sentence_boundary


class TestSnippetTruncation:
    """句子边界截断测试"""

    def test_no_truncation_needed(self):
        """短文本无边界需求"""
        text = "Short text"
        pos = find_sentence_boundary(text, 0.0)
        assert pos == -1

    def test_truncate_at_paragraph(self):
        """在段落边界截断"""
        text = "Paragraph 1.\n\nParagraph 2.\n\nParagraph 3."
        truncated = text[:30]
        pos = find_sentence_boundary(truncated, 0.3)
        assert pos > 0
        assert truncated[:pos].rstrip() == "Paragraph 1.\n\nParagraph 2."

    def test_truncate_at_chinese_period(self):
        """在中文句号截断"""
        text = "第一句话。" * 20
        truncated = text[:30]
        pos = find_sentence_boundary(truncated, 0.3)
        assert pos > 0
        assert truncated[:pos].endswith("。")

    def test_truncate_at_english_period(self):
        """在英文句号截断"""
        text = "First. Second. Third. Fourth."
        truncated = text[:20]
        pos = find_sentence_boundary(truncated, 0.3)
        assert pos > 0

    def test_no_boundary_found(self):
        """无合适边界时返回 -1"""
        text = "x" * 100
        pos = find_sentence_boundary(text[:50], 0.6)
        assert pos == -1

    def test_mixed_language(self):
        """中英混合文本"""
        text = "English sentence. 中文句子。Another English. 另一个中文。"
        truncated = text[:40]
        pos = find_sentence_boundary(truncated, 0.3)
        assert pos > 0
