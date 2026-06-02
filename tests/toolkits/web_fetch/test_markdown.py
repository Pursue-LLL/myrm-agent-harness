"""MarkdownGenerator 测试"""

import pytest

from myrm_agent_harness.toolkits.web_fetch.content_pruning import ContentPruningFilter
from myrm_agent_harness.toolkits.web_fetch.markdown_generator import MarkdownGenerator, MarkdownResult


def test_markdown_generator_initialization():
    """测试 Markdown 生成器初始化"""
    content_filter = ContentPruningFilter()
    generator = MarkdownGenerator(content_filter=content_filter)

    assert generator.content_filter is not None


def test_markdown_result_dataclass():
    """测试 MarkdownResult 数据类"""
    result = MarkdownResult(raw_markdown="# Title", fit_markdown="## Fit")

    assert result.raw_markdown == "# Title"
    assert result.fit_markdown == "## Fit"
    assert result.markdown_with_citations == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
