"""ContentPipeline 测试"""

import pytest

from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import FetcherType, FetchResult
from myrm_agent_harness.toolkits.web_fetch.pipeline import ContentPipeline


def test_pipeline_initialization():
    """测试管道初始化"""
    pipeline = ContentPipeline()

    assert pipeline._md_generator is not None


def test_pipeline_raw_mode():
    """测试原始 Markdown 模式"""
    pipeline = ContentPipeline(use_raw_markdown=True)

    fetch_result = FetchResult(
        html="<html><body><h1>Title</h1><p>Content with enough text to pass minimum length threshold</p></body></html>",
        url="https://example.com",
        status_code=200,
    )

    doc = pipeline.process(fetch_result)

    assert doc is not None
    assert "Title" in doc.page_content
    assert doc.metadata["url"] == "https://example.com"


def test_pipeline_pruned_mode():
    """测试剪枝模式"""
    pipeline = ContentPipeline(use_raw_markdown=False)

    fetch_result = FetchResult(
        html="""
        <html>
            <body>
                <nav>Navigation</nav>
                <main>
                    <article>
                        <h1>Main Title</h1>
                        <p>Important content here with enough text to pass minimum length threshold. This is a longer paragraph to ensure the content is substantial enough for the content pipeline to process correctly. We need more text here to simulate a real article with meaningful content.</p>
                        <p>Another paragraph with additional content to make sure we meet all the thresholds and quality checks in the pipeline. This helps ensure that the pruning filter recognizes this as valuable content worth keeping.</p>
                    </article>
                </main>
                <footer>Footer</footer>
            </body>
        </html>
        """,
        url="https://example.com",
        status_code=200,
    )

    doc = pipeline.process(fetch_result)

    assert doc is not None
    assert doc.page_content != ""


def test_pipeline_with_empty_html():
    """测试空 HTML 处理"""
    pipeline = ContentPipeline()

    fetch_result = FetchResult(html="", url="https://example.com", status_code=200)

    doc = pipeline.process(fetch_result)

    assert doc is None


def test_pipeline_stealth_short_content():
    """测试 stealth 模式下内容过短的回退逻辑"""
    pipeline = ContentPipeline(use_raw_markdown=False)

    fetch_result = FetchResult(
        html="<html><body><article><p>" + ("This is test content. " * 20) + "</p></article></body></html>",
        url="https://example.com",
        status_code=200,
        fetcher_type=FetcherType.STEALTH,
    )

    doc = pipeline.process(fetch_result)
    assert doc is not None
    assert len(doc.page_content) > 0


def test_pipeline_passes_error_page_through():
    """Pipeline converts error pages to Document — anti-bot detection is in engine layer."""
    pipeline = ContentPipeline()

    fetch_result = FetchResult(
        html="""<html>
            <head><title>404 Not Found</title></head>
            <body>
                <h1>404 Not Found</h1>
                <p>The page you are looking for does not exist. This is an error page with sufficient content.</p>
            </body>
        </html>""",
        url="https://example.com",
        status_code=404,
    )

    doc = pipeline.process(fetch_result)
    assert doc is not None
    assert "404" in doc.page_content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
