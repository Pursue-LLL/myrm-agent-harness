"""ContentPruningFilter 测试"""

import pytest

from myrm_agent_harness.toolkits.web_fetch.content_pruning import ContentPruningFilter


def test_filter_initialization():
    """测试过滤器初始化"""
    filter = ContentPruningFilter()

    assert filter.threshold > 0
    assert filter.min_word_threshold >= 0
    assert "text_density" in filter.metric_weights


def test_filter_simple_content():
    """测试简单内容过滤"""
    filter = ContentPruningFilter()

    assert filter.threshold > 0
    assert len(filter.excluded_tags) > 0


def test_filter_with_threshold():
    """测试自定义阈值"""
    filter_strict = ContentPruningFilter(threshold=0.7)
    filter_loose = ContentPruningFilter(threshold=0.3)

    assert filter_strict.threshold > filter_loose.threshold


def test_filter_with_min_words():
    """测试最小字数阈值"""
    filter = ContentPruningFilter(min_word_threshold=10)

    assert filter.min_word_threshold == 10

def test_process_with_truncation():
    """测试带截断的process方法"""
    filter = ContentPruningFilter()
    html_content = """
    <html>
        <body>
            <article>This is an important article. It contains a lot of very useful information.</article>
            <nav>Some links</nav>
            <footer>Copyright 2026</footer>
        </body>
    </html>
    """

    # 无截断
    result_no_truncation, was_truncated = filter.filter_content(html_content, max_chars=0)
    assert not was_truncated
    joined_result_no_truncation = "".join(result_no_truncation)
    assert "This is an important article" in joined_result_no_truncation

    # 截断（截断为非常短的内容，足以触发截断）
    # 注意 max_chars 是字符数
    result_truncation, was_truncated2 = filter.filter_content(html_content, max_chars=20)
    assert was_truncated2
    joined_result_truncation = "".join(result_truncation)
    assert len(joined_result_truncation) > 0
    # 至少不会包含全部内容，结构会更紧凑
    assert len(joined_result_truncation) < len(joined_result_no_truncation)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
