"""Web Fetch Tools import tests."""

from myrm_agent_harness.toolkits.web_fetch.engine import CrawlEngine


def test_web_fetch_tools_import() -> None:
    """Test CrawlEngine class can be imported."""
    assert CrawlEngine is not None
    assert hasattr(CrawlEngine, "crawl")
    assert hasattr(CrawlEngine, "crawl_many")
    assert hasattr(CrawlEngine, "shutdown")
