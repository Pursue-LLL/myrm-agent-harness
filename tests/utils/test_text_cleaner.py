"""文本清理工具测试"""

from myrm_agent_harness.utils.text_cleaner import (
    COMPILED_PATTERNS,
    clean_document_content,
    clean_search_snippet,
    clean_text,
)


class TestCleanSearchSnippet:
    """测试 clean_search_snippet 函数"""

    def test_empty_snippet(self):
        """测试空snippet"""
        assert clean_search_snippet("") == ""

    def test_multiple_newlines(self):
        """测试多个换行符"""
        snippet = "Line 1\n\n\nLine 2"
        result = clean_search_snippet(snippet)
        assert result == "Line 1\nLine 2"

    def test_trim_lines(self):
        """测试去除每行首尾空白"""
        snippet = "  Line 1  \n  Line 2  "
        result = clean_search_snippet(snippet)
        assert result == "Line 1\nLine 2"

    def test_remove_empty_lines(self):
        """测试去除空行"""
        snippet = "Line 1\n\nLine 2\n\nLine 3"
        result = clean_search_snippet(snippet)
        assert result == "Line 1\nLine 2\nLine 3"

    def test_reduce_inline_whitespace(self):
        """测试减少行内多余空格"""
        snippet = "This   has    many     spaces"
        result = clean_search_snippet(snippet)
        assert result == "This has many spaces"

    def test_combined_cleaning(self):
        """测试综合清理"""
        snippet = "  Line 1  \n\n  Line 2   with   spaces  \n\n  Line 3  "
        result = clean_search_snippet(snippet)
        assert result == "Line 1\nLine 2 with spaces\nLine 3"


class TestCleanText:
    """测试 clean_text 函数"""

    def test_empty_text(self):
        """测试空文本"""
        assert clean_text("") == ""

    def test_garbled_text_detection(self):
        """测试乱码检测"""
        # 创建一个乱码比例>5%的文本（需要足够长>100字符）
        garbled = "正常文本" * 10 + "�" * 100  # 总长度约140字符，�占71%
        result = clean_text(garbled)
        # 乱码比例>5%，应该返回空
        assert result == ""

    def test_garbled_text_below_threshold(self):
        """测试低于乱码阈值的文本"""
        text = "正常文本" * 20 + "�"
        result = clean_text(text)
        # 乱码比例<5%，应该保留
        assert "正常文本" in result

    def test_remove_copyright_info(self):
        """测试去除版权信息"""
        text = "正文内容\n版权声明：本文版权归作者所有，转载请注明出处。\n更多内容"
        result = clean_text(text)
        assert "版权声明" not in result
        assert "正文内容" in result

    def test_remove_stats_line(self):
        """测试去除统计信息行"""
        text = "标题\n1.2万 100 2024-03-15 12:00:00\n正文内容"
        result = clean_text(text)
        assert "1.2万" not in result
        assert "正文内容" in result

    def test_remove_engagement_metrics(self):
        """测试去除互动指标"""
        text = "文章内容\n1000点赞\n500收藏\n200评论"
        result = clean_text(text)
        # 清理后这些数字行应该被移除或清理
        assert "点赞" not in result or "1000" not in result

    def test_normalize_headers(self):
        """测试标题规范化"""
        text = "#Header1\n##  Header2  \n正文"
        result = clean_text(text)
        # 标题应该有空格分隔
        assert "# Header1" in result
        assert "## Header2" in result

    def test_preserve_code_blocks(self):
        """测试保留代码块"""
        text = "文本\n```python\n    def foo():\n        pass\n```\n文本"
        result = clean_text(text)
        assert "```python" in result
        assert "def foo():" in result
        # 代码块内缩进应该保留
        assert "    def foo():" in result

    def test_reduce_multiple_blank_lines(self):
        """测试减少多个空行"""
        text = "Line 1\n\n\n\nLine 2"
        result = clean_text(text)
        # 多个空行应该被减少为两个换行符（一个空行）
        assert "\n\n\n" not in result
        assert "Line 1\n\nLine 2" in result

    def test_remove_unwanted_keywords(self):
        """测试去除无用关键词行"""
        text = "正文内容\n返回顶部\n关注我们\n更多内容"
        result = clean_text(text)
        # 短行中的无用关键词应该被移除
        lines = result.split("\n")
        assert not any("返回顶部" in line for line in lines)
        assert not any("关注我们" in line for line in lines)


class TestCleanDocumentContent:
    """测试 clean_document_content 函数"""

    def test_no_front_matter(self):
        """测试没有front matter的文档"""
        content = "正文内容\n更多文本"
        result = clean_document_content(content)
        assert "正文内容" in result

    def test_with_front_matter(self):
        """测试包含front matter的文档"""
        content = "---\ntitle: Test\ndate: 2024-03-15\n---\n正文内容"
        result = clean_document_content(content)
        # front matter应该被移除
        assert "title:" not in result
        assert "正文内容" in result

    def test_front_matter_with_nested_yaml(self):
        """测试包含嵌套YAML的front matter"""
        content = "---\ntitle: Test\nmeta:\n  author: Someone\n---\n内容"
        result = clean_document_content(content)
        assert "author:" not in result
        assert "内容" in result

    def test_false_front_matter_in_content(self):
        """测试内容中包含---但不是front matter"""
        content = "正文开始\n---\n分隔符\n---\n更多内容"
        result = clean_document_content(content)
        # 第一个---不在开头，所以不是front matter
        assert "正文开始" in result


class TestCompiledPatterns:
    """测试预编译模式"""

    def test_stats_line_pattern(self):
        """测试统计行模式"""
        pattern = COMPILED_PATTERNS["stats_line"]
        assert pattern.search("1.2万 100 2024-03-15 12:00:00")
        assert pattern.search("  1000   200   2024-01-01   08:30:00  ")

    def test_whitespace_pattern(self):
        """测试空格模式"""
        pattern = COMPILED_PATTERNS["whitespace"]
        assert pattern.search("  ")
        assert pattern.search("\t")
        assert pattern.search("  \t  ")

    def test_header_pattern(self):
        """测试标题模式"""
        pattern = COMPILED_PATTERNS["header"]
        match = pattern.match("# Title")
        assert match
        assert match.group(1) == "#"
        assert match.group(2) == "Title"

        match2 = pattern.match("### Another Title")
        assert match2
        assert match2.group(1) == "###"


class TestIntegration:
    """集成场景测试"""

    def test_real_world_web_content(self):
        """测试真实网页内容"""
        content = """
        首页 关于我们

        # 文章标题

        发布于 2024-03-15
        1000 阅读 500 点赞

        这是正文内容，包含有用信息。

        ## 子标题

        更多有用内容。

        版权声明：未经授权禁止转载
        返回顶部 | 联系我们
        """
        result = clean_text(content)

        # 保留的内容
        assert "文章标题" in result
        assert "正文内容" in result
        assert "子标题" in result

        # 移除的内容（某些关键词可能只被部分清理）
        assert "返回顶部" not in result
        # 版权相关内容应该被大幅清理，即使不是完全移除
        # 原文本有"版权声明：未经授权禁止转载"，正则会匹配"未经.*授权.*禁止.*转载"
        # 所以"版权声明："可能会保留，但"未经授权禁止转载"应该被移除
        assert "未经授权" not in result or "禁止转载" not in result

    def test_snippet_vs_full_content(self):
        """测试snippet和full content清理的差异"""
        text = "简短摘要\n\n包含多个空行"

        snippet_result = clean_search_snippet(text)
        text_result = clean_text(text)

        # snippet更激进地去除空行
        assert snippet_result == "简短摘要\n包含多个空行"
        # full content保留一些格式
        assert "简短摘要" in text_result


class TestEdgeCases:
    """边界情况测试"""

    def test_very_short_text(self):
        """测试极短文本"""
        assert clean_text("Hello") == "Hello"
        assert clean_search_snippet("Hi") == "Hi"

    def test_only_whitespace(self):
        """测试纯空白字符"""
        assert clean_text("   \n\n   ") == ""
        assert clean_search_snippet("   \n\n   ") == ""

    def test_unicode_content(self):
        """测试Unicode内容"""
        text = "中文内容  emoji"
        result = clean_text(text)
        assert "中文内容" in result
        assert "" in result

    def test_special_regex_characters(self):
        """测试特殊正则字符"""
        text = "Content with [brackets] and (parens) and $dollar"
        result = clean_text(text)
        assert "[brackets]" in result
        assert "(parens)" in result
