"""Tests for RefNotFoundError structured diagnostics and metrics."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.exceptions import RefNotFoundError
from myrm_agent_harness.toolkits.browser.session.interactor import Interactor
from myrm_agent_harness.toolkits.browser.snapshot import RefInfo


@pytest.fixture
def refs_map() -> dict[str, RefInfo]:
    """Sample refs with various roles and names."""
    return {
        "e0": RefInfo(role="button", name="Submit", nth=None, bbox={}, position=""),
        "e1": RefInfo(role="button", name="Cancel", nth=None, bbox={}, position=""),
        "e2": RefInfo(role="textbox", name="Username", nth=None, bbox={}, position=""),
        "e3": RefInfo(role="textbox", name="Password", nth=None, bbox={}, position=""),
        "e4": RefInfo(role="link", name="Forgot password", nth=None, bbox={}, position=""),
    }


@pytest.fixture
def mock_page() -> Any:
    """Mock Playwright Page."""
    return MagicMock()


@pytest.fixture
def interactor(mock_page: Any, refs_map: dict[str, RefInfo]) -> Interactor:
    """Create Interactor with mocked page and refs."""
    return Interactor(mock_page, refs_map, last_snapshot_url=None)


@pytest.mark.asyncio
async def test_ref_not_found_structured_error(interactor: Interactor) -> None:
    """Test RefNotFoundError contains structured diagnostic information."""
    with pytest.raises(RefNotFoundError) as exc_info:
        await interactor.interact("click", "e99")

    error = exc_info.value
    assert error.ref == "e99"
    assert error.total_refs == 5
    assert error.ref_range == "e0-e4"
    assert "Ref not found: e99" in str(error)
    assert "browser_snapshot(diff=False)" in str(error)


@pytest.mark.asyncio
async def test_get_context_refs(interactor: Interactor, refs_map: dict[str, RefInfo]) -> None:
    """Test getting context refs for LLM diagnosis."""
    context = interactor._get_context_refs(max_total=15)

    assert len(context) >= 3
    assert all("ref" in r and "role" in r and "name" in r for r in context)
    unique_roles = {r["role"] for r in context}
    assert len(unique_roles) >= 2


@pytest.mark.asyncio
async def test_smart_sampling_prioritizes_named_refs(mock_page: Any) -> None:
    """Test context refs prioritize elements with names over empty names."""
    refs = {
        "e0": RefInfo(role="button", name="", nth=None, bbox={}, position=""),
        "e1": RefInfo(role="button", name="", nth=None, bbox={}, position=""),
        "e2": RefInfo(role="button", name="", nth=None, bbox={}, position=""),
        "e3": RefInfo(role="button", name="Submit", nth=None, bbox={}, position=""),
        "e4": RefInfo(role="button", name="Cancel", nth=None, bbox={}, position=""),
        "e5": RefInfo(role="link", name="", nth=None, bbox={}, position=""),
        "e6": RefInfo(role="link", name="Home", nth=None, bbox={}, position=""),
    }
    interactor = Interactor(mock_page, refs, last_snapshot_url=None)

    context = interactor._get_context_refs(max_total=6)

    button_refs = [r for r in context if r["role"] == "button"]
    assert len(button_refs) >= 2
    assert button_refs[0]["name"] == "Submit", "First button should have name"
    assert button_refs[1]["name"] == "Cancel", "Second button should have name"

    link_refs = [r for r in context if r["role"] == "link"]
    assert len(link_refs) >= 1
    assert link_refs[0]["name"] == "Home", "First link should have name"


@pytest.mark.asyncio
async def test_ref_not_found_metrics_tracking(interactor: Interactor) -> None:
    """Test metrics are updated when ref not found."""
    assert interactor.metrics.total_failures == 0

    with pytest.raises(RefNotFoundError):
        await interactor.interact("click", "e99")

    assert interactor.metrics.total_failures == 1
    assert interactor.metrics.failure_refs["e99"] == 1

    with pytest.raises(RefNotFoundError):
        await interactor.interact("click", "e99")

    assert interactor.metrics.total_failures == 2
    assert interactor.metrics.failure_refs["e99"] == 2


@pytest.mark.asyncio
async def test_ref_not_found_context_refs_included(interactor: Interactor, refs_map: dict[str, RefInfo]) -> None:
    """Test RefNotFoundError includes context refs for LLM diagnosis."""
    with pytest.raises(RefNotFoundError) as exc_info:
        await interactor.interact("click", "e99")

    error = exc_info.value
    assert len(error.context_refs) >= 3
    roles = {r["role"] for r in error.context_refs}
    assert len(roles) >= 2


@pytest.mark.asyncio
async def test_ref_not_found_empty_refs(mock_page: Any) -> None:
    """Test RefNotFoundError when no refs exist at all."""
    empty_interactor = Interactor(mock_page, {}, last_snapshot_url=None)

    with pytest.raises(RefNotFoundError) as exc_info:
        await empty_interactor.interact("click", "nonexistent")

    error = exc_info.value
    assert error.context_refs == []
    assert error.total_refs == 0
    assert empty_interactor.metrics.total_failures == 1


@pytest.mark.asyncio
async def test_metrics_basic_tracking(interactor: Interactor, refs_map: dict[str, RefInfo]) -> None:
    """Test metrics track total failures and frequency."""
    with pytest.raises(RefNotFoundError):
        await interactor.interact("click", "e99")

    assert interactor.metrics.total_failures == 1
    assert interactor.metrics.failure_refs["e99"] == 1

    with pytest.raises(RefNotFoundError):
        await interactor.interact("click", "e98")

    assert interactor.metrics.total_failures == 2
    assert interactor.metrics.failure_refs["e98"] == 1


@pytest.mark.asyncio
async def test_context_refs_max_total_early_return(mock_page: Any) -> None:
    """Test context refs early return when approaching max_total."""
    refs = {}
    for i in range(20):
        refs[f"e{i}"] = RefInfo(role=f"role{i}", name=f"Name{i}", nth=None, bbox={}, position="")

    interactor = Interactor(mock_page, refs)

    context = interactor._get_context_refs(max_total=3)

    assert len(context) <= 3
    assert all("ref" in r and "role" in r and "name" in r for r in context)


@pytest.mark.asyncio
async def test_ref_not_found_url_change_detection(mock_page: Any, refs_map: dict[str, RefInfo]) -> None:
    """Test RefNotFoundError detects page navigation and provides smart suggestions."""
    mock_page.url = "https://example.com/login"
    interactor = Interactor(mock_page, refs_map, last_snapshot_url=None)

    interactor.update_refs(refs_map, last_snapshot_url="https://example.com/login")

    mock_page.url = "https://example.com/dashboard"

    with pytest.raises(RefNotFoundError) as exc_info:
        await interactor.interact("click", "e99")

    error = exc_info.value
    error_msg = str(error)

    assert "Page has navigated from https://example.com/login to https://example.com/dashboard" in error_msg
    assert "Call browser_snapshot(diff=False) to get new page refs" in error_msg


@pytest.mark.asyncio
async def test_ref_not_found_url_unchanged(mock_page: Any, refs_map: dict[str, RefInfo]) -> None:
    """Test RefNotFoundError suggests dynamic content when URL unchanged."""
    mock_page.url = "https://example.com/page"
    interactor = Interactor(mock_page, refs_map, last_snapshot_url=None)

    interactor.update_refs(refs_map, last_snapshot_url="https://example.com/page")

    with pytest.raises(RefNotFoundError) as exc_info:
        await interactor.interact("click", "e99")

    error = exc_info.value
    error_msg = str(error)

    assert "Page URL unchanged" in error_msg
    assert "dynamic content loaded" in error_msg
    assert "browser_snapshot(diff=False)" in error_msg


@pytest.mark.asyncio
async def test_ref_not_found_no_url_history(mock_page: Any, refs_map: dict[str, RefInfo]) -> None:
    """Test RefNotFoundError falls back to generic suggestion when no URL history."""
    mock_page.url = "https://example.com/page"
    interactor = Interactor(mock_page, refs_map, last_snapshot_url=None)

    with pytest.raises(RefNotFoundError) as exc_info:
        await interactor.interact("click", "e99")

    error = exc_info.value
    error_msg = str(error)

    assert "browser_snapshot(diff=False)" in error_msg
    assert "Page structure may have changed" in error_msg


@pytest.mark.asyncio
async def test_update_refs_captures_url(mock_page: Any, refs_map: dict[str, RefInfo]) -> None:
    """Test update_refs captures snapshot URL for later diagnosis."""
    mock_page.url = "https://example.com/initial"
    interactor = Interactor(mock_page, refs_map, last_snapshot_url=None)

    assert interactor._last_snapshot_url is None

    interactor.update_refs(refs_map, last_snapshot_url="https://example.com/snapshot1")
    assert interactor._last_snapshot_url == "https://example.com/snapshot1"

    interactor.update_refs(refs_map, last_snapshot_url="https://example.com/snapshot2")
    assert interactor._last_snapshot_url == "https://example.com/snapshot2"


@pytest.mark.asyncio
async def test_update_refs_without_url_preserves_state(mock_page: Any, refs_map: dict[str, RefInfo]) -> None:
    """Test update_refs preserves last_snapshot_url when not provided."""
    mock_page.url = "https://example.com/current"
    interactor = Interactor(mock_page, refs_map, last_snapshot_url="https://example.com/preserved")

    interactor.update_refs(refs_map)
    assert interactor._last_snapshot_url == "https://example.com/preserved"


@pytest.mark.asyncio
async def test_url_normalization_trailing_slash(mock_page: Any, refs_map: dict[str, RefInfo]) -> None:
    """Test URL normalization treats trailing slash as same page."""
    mock_page.url = "https://example.com/page/"
    interactor = Interactor(mock_page, refs_map, last_snapshot_url=None)

    interactor.update_refs(refs_map, last_snapshot_url="https://example.com/page")

    with pytest.raises(RefNotFoundError) as exc_info:
        await interactor.interact("click", "e99")

    error_msg = str(exc_info.value)
    assert "Page URL unchanged" in error_msg
    assert "dynamic content loaded" in error_msg
    assert "browser_snapshot(diff=False)" in error_msg


@pytest.mark.asyncio
async def test_url_change_hash_only(mock_page: Any, refs_map: dict[str, RefInfo]) -> None:
    """Test hash-only changes are classified as anchor scrolling."""
    mock_page.url = "https://example.com/page#section2"
    interactor = Interactor(mock_page, refs_map, last_snapshot_url=None)

    interactor.update_refs(refs_map, last_snapshot_url="https://example.com/page#section1")

    with pytest.raises(RefNotFoundError) as exc_info:
        await interactor.interact("click", "e99")

    error_msg = str(exc_info.value)
    assert "Page scrolled to anchor" in error_msg
    assert "section1" in error_msg and "section2" in error_msg
    assert "browser_snapshot(diff=False)" in error_msg


@pytest.mark.asyncio
async def test_url_change_query_params(mock_page: Any, refs_map: dict[str, RefInfo]) -> None:
    """Test query parameter changes are classified correctly."""
    mock_page.url = "https://example.com/search?page=2"
    interactor = Interactor(mock_page, refs_map, last_snapshot_url=None)

    interactor.update_refs(refs_map, last_snapshot_url="https://example.com/search?page=1")

    with pytest.raises(RefNotFoundError) as exc_info:
        await interactor.interact("click", "e99")

    error_msg = str(exc_info.value)
    assert "Query params changed" in error_msg
    assert "page=1" in error_msg and "page=2" in error_msg
    assert "refresh dynamic content refs" in error_msg


@pytest.mark.asyncio
async def test_url_normalization_case_insensitive_scheme_host(mock_page: Any, refs_map: dict[str, RefInfo]) -> None:
    """Test URL normalization is case-insensitive for scheme and host."""
    mock_page.url = "HTTPS://EXAMPLE.COM/page"
    interactor = Interactor(mock_page, refs_map, last_snapshot_url=None)

    interactor.update_refs(refs_map, last_snapshot_url="https://example.com/page")

    with pytest.raises(RefNotFoundError) as exc_info:
        await interactor.interact("click", "e99")

    error_msg = str(exc_info.value)
    assert "Page URL unchanged" in error_msg


@pytest.mark.asyncio
async def test_url_change_path_navigation(mock_page: Any, refs_map: dict[str, RefInfo]) -> None:
    """Test path changes are classified as full navigation."""
    mock_page.url = "https://example.com/dashboard/settings"
    interactor = Interactor(mock_page, refs_map, last_snapshot_url=None)

    interactor.update_refs(refs_map, last_snapshot_url="https://example.com/dashboard")

    with pytest.raises(RefNotFoundError) as exc_info:
        await interactor.interact("click", "e99")

    error_msg = str(exc_info.value)
    assert "Page has navigated from" in error_msg
    assert "/dashboard" in error_msg and "/dashboard/settings" in error_msg
    assert "get new page refs" in error_msg


def test_classify_url_change_path() -> None:
    """Test _classify_url_change detects path changes."""
    change_type, last_norm, curr_norm = RefNotFoundError._classify_url_change(
        "https://example.com/page1", "https://example.com/page2"
    )
    assert change_type == "path"
    assert last_norm == "https://example.com/page1"
    assert curr_norm == "https://example.com/page2"


def test_classify_url_change_query() -> None:
    """Test _classify_url_change detects query parameter changes."""
    change_type, last_norm, curr_norm = RefNotFoundError._classify_url_change(
        "https://example.com/search?q=foo", "https://example.com/search?q=bar"
    )
    assert change_type == "query"
    assert "q=foo" in last_norm
    assert "q=bar" in curr_norm


def test_classify_url_change_hash() -> None:
    """Test _classify_url_change detects hash changes."""
    change_type, _, _ = RefNotFoundError._classify_url_change(
        "https://example.com/page#intro", "https://example.com/page#pricing"
    )
    assert change_type == "hash"


def test_classify_url_change_trailing_slash_normalized() -> None:
    """Test trailing slash is normalized (treated as same page)."""
    change_type, _, _ = RefNotFoundError._classify_url_change("https://example.com/page", "https://example.com/page/")
    assert change_type == "none"


def test_classify_url_change_case_insensitive() -> None:
    """Test scheme and host are case-insensitive."""
    change_type, _, _ = RefNotFoundError._classify_url_change("HTTPS://EXAMPLE.COM/page", "https://example.com/page")
    assert change_type == "none"


def test_classify_url_change_identical_fast_path() -> None:
    """Test fast-path optimization for identical URLs."""
    url = "https://example.com/page?query=value#section"
    change_type, last_norm, curr_norm = RefNotFoundError._classify_url_change(url, url)

    assert change_type == "none"
    assert last_norm == url
    assert curr_norm == url


# =============================================================================
# New Metrics Features
# =============================================================================


@pytest.mark.asyncio
async def test_metrics_failure_rate_calculation(mock_page: Any, refs_map: dict[str, RefInfo]) -> None:
    """Test failure rate is calculated correctly."""
    mock_page.url = "https://example.com/page"
    interactor = Interactor(mock_page, refs_map, last_snapshot_url=None)

    assert interactor.metrics.failure_rate == 0.0

    interactor._metrics.total_interactions = 10
    interactor._metrics.total_failures = 0
    assert interactor.metrics.failure_rate == 0.0

    with pytest.raises(RefNotFoundError):
        await interactor.interact("click", "e99")

    assert interactor.metrics.total_interactions == 11
    assert interactor.metrics.total_failures == 1
    assert abs(interactor.metrics.failure_rate - 1 / 11) < 0.001

    with pytest.raises(RefNotFoundError):
        await interactor.interact("click", "e98")

    assert interactor.metrics.total_interactions == 12
    assert interactor.metrics.total_failures == 2
    assert abs(interactor.metrics.failure_rate - 2 / 12) < 0.001


@pytest.mark.asyncio
async def test_metrics_top_failed_refs(mock_page: Any, refs_map: dict[str, RefInfo]) -> None:
    """Test top_failed_refs returns sorted list."""
    mock_page.url = "https://example.com/page"
    interactor = Interactor(mock_page, refs_map, last_snapshot_url=None)

    with pytest.raises(RefNotFoundError):
        await interactor.interact("click", "e99")

    with pytest.raises(RefNotFoundError):
        await interactor.interact("click", "e99")

    with pytest.raises(RefNotFoundError):
        await interactor.interact("click", "e98")

    top_refs = interactor.metrics.top_failed_refs
    assert len(top_refs) == 2
    assert top_refs[0] == ("e99", 2)
    assert top_refs[1] == ("e98", 1)


@pytest.mark.asyncio
async def test_metrics_failure_by_action(mock_page: Any, refs_map: dict[str, RefInfo]) -> None:
    """Test failure_by_action tracks failures per action type."""
    mock_page.url = "https://example.com/page"
    interactor = Interactor(mock_page, refs_map, last_snapshot_url=None)

    with pytest.raises(RefNotFoundError):
        await interactor.interact("click", "e99")

    with pytest.raises(RefNotFoundError):
        await interactor.interact("fill", "e98", "text")

    with pytest.raises(RefNotFoundError):
        await interactor.interact("click", "e97")

    assert interactor.metrics.failure_by_action["click"] == 2
    assert interactor.metrics.failure_by_action["fill"] == 1
    assert interactor.metrics.top_failed_actions == [("click", 2), ("fill", 1)]


@pytest.mark.asyncio
async def test_metrics_recent_failure_rate(mock_page: Any, refs_map: dict[str, RefInfo]) -> None:
    """Test recent_failure_rate tracks sliding window of last 100 interactions."""
    from unittest.mock import AsyncMock

    mock_page.url = "https://example.com/page"
    mock_page.locator.return_value.click = AsyncMock()
    interactor = Interactor(mock_page, refs_map, last_snapshot_url=None)

    assert interactor.metrics.recent_failure_rate == 0.0

    for _i in range(10):
        with pytest.raises(RefNotFoundError):
            await interactor.interact("click", "e99")

    assert interactor.metrics.total_interactions == 10
    assert interactor.metrics.recent_failure_rate == 1.0

    for _i in range(10):
        interactor._metrics.record_interaction(failed=False)

    assert interactor.metrics.total_interactions == 20
    assert interactor.metrics.recent_failure_rate == 0.5

    for _i in range(80):
        interactor._metrics.record_interaction(failed=False)

    assert interactor.metrics.total_interactions == 100
    assert interactor.metrics.recent_failure_rate == 0.1


@pytest.mark.asyncio
async def test_metrics_cache_invalidation(mock_page: Any, refs_map: dict[str, RefInfo]) -> None:
    """Test top_failed_refs cache is invalidated on new failures."""
    mock_page.url = "https://example.com/page"
    interactor = Interactor(mock_page, refs_map, last_snapshot_url=None)

    with pytest.raises(RefNotFoundError):
        await interactor.interact("click", "e99")

    first_top = interactor.metrics.top_failed_refs
    assert first_top[0] == ("e99", 1)

    second_top = interactor.metrics.top_failed_refs
    assert first_top is second_top

    with pytest.raises(RefNotFoundError):
        await interactor.interact("click", "e98")

    third_top = interactor.metrics.top_failed_refs
    assert third_top is not second_top
    assert len(third_top) == 2
