"""MarkdownGenerator 测试"""

import pytest

from myrm_agent_harness.toolkits.web_fetch.processing.content_pruning import ContentPruningFilter
from myrm_agent_harness.toolkits.web_fetch.processing.markdown_generator import MarkdownGenerator, MarkdownResult


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


def test_html_deep_nesting_depth_limit_protection():
    """测试极深嵌套 DOM (如 600 层 div) 时熔断保护，防止 RecursionError 栈溢出"""
    from myrm_agent_harness.toolkits.web_fetch.processing.html_to_markdown import CustomHTML2Text

    depth = 600
    inner_text = "Core content deep inside 600 nested layers"
    html_content = ("<div>" * depth) + inner_text + ("</div>" * depth)

    converter = CustomHTML2Text()
    # 转换必须在合理时间内顺利返回，且不得抛出 RecursionError
    result = converter.handle(html_content)

    assert inner_text in result
    assert converter._current_depth == 0


def test_html_standard_conversion_fidelity():
    """测试正常多级格式的转换保真度"""
    from myrm_agent_harness.toolkits.web_fetch.processing.html_to_markdown import CustomHTML2Text

    html_content = """
    <html>
        <body>
            <h1>Section Title</h1>
            <p>This is a paragraph with <strong>bold</strong> and <em>italic</em>.</p>
            <ul>
                <li>Item 1</li>
                <li>Item 2</li>
            </ul>
        </body>
    </html>
    """
    converter = CustomHTML2Text()
    result = converter.handle(html_content)

    assert "# Section Title" in result
    assert "**bold**" in result
    assert "_italic_" in result
    assert "* Item 1" in result or "- Item 1" in result or "Item 1" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
