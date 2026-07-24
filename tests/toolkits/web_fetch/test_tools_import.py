"""Web Fetch Tools import tests."""

from myrm_agent_harness.toolkits.web_fetch.engine import FetchEngine


def test_web_fetch_tools_import() -> None:
    """Test FetchEngine class can be imported."""
    assert FetchEngine is not None
    assert hasattr(FetchEngine, "crawl")
    assert hasattr(FetchEngine, "crawl_many")
    assert hasattr(FetchEngine, "shutdown")
