"""Boundary tests for browser page analysis recommendations."""

from myrm_agent_harness.toolkits.browser.session.page_analyzer import PageAnalyzer


def test_page_analyzer_recommendation():
    """Test page analyzer recommendation boundaries."""
    analyzer = PageAnalyzer(page=None)  # type: ignore[arg-type]

    selector, savings = analyzer._compute_recommendation(49, [("#main", "<main> region", 20)])
    assert selector == ""
    assert savings == "0%"

    selector, savings = analyzer._compute_recommendation(100, [])
    assert selector == ""
    assert savings == "0%"

    selector, savings = analyzer._compute_recommendation(
        100,
        [
            ("#main", "<main> region", 70),
            ("#sidebar", "<nav> region", 20),
        ],
    )
    assert selector == "#main"
    assert savings == "30%"

    selector, savings = analyzer._compute_recommendation(100, [("#form", "<form> region", 50)])
    assert selector == "#form"
    assert savings == "50%"
