"""LangChain tool for local browser data search.


[INPUT]
- chromium_locator::discover_browsers (POS: browser detection)
- profile_enumerator::enumerate_profiles (POS: profile enumeration)
- bookmark_searcher::search_bookmarks (POS: bookmark search)
- history_searcher::search_history (POS: history search)
- types::SearchSource, SortOrder, SearchResults (POS: search types and results)
- langchain.tools::tool (POS: LangChain tool decorator)
- pydantic::BaseModel, Field (POS: parameter validation)

[OUTPUT]
- create_local_browser_data_tool: factory function to create local browser data search tool

[POS]
LangChain interface layer for local browser data search tool. Wraps underlying search capabilities
(bookmarks + history) into a single Agent tool. Pure thin layer, zero business logic.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from langchain.tools import tool
from pydantic import BaseModel, Field

from myrm_agent_harness.observability.diagnostics.manager import register_diagnostic
from myrm_agent_harness.observability.diagnostics.protocols import HealthReport

from .bookmark_searcher import search_bookmarks
from .chromium_locator import discover_browsers
from .history_searcher import search_history
from .profile_enumerator import enumerate_profiles
from .types import SearchResults, SearchSource, SortOrder

logger = logging.getLogger(__name__)

_SINCE_PATTERN = re.compile(r"^(\d+)([dhm])$")
_SINCE_UNITS = {"d": "days", "h": "hours", "m": "minutes"}


async def check_local_browser_health() -> HealthReport:
    """Check health of local browser data tool"""
    try:
        browsers = discover_browsers()
        if not browsers:
            return HealthReport(
                component_name="LocalBrowserData",
                status="warn",
                message="Local browser data feature is not available.",
                detail="No supported local browsers (Chrome/Edge) found.",
                fix_suggestion="Install Google Chrome or Microsoft Edge to use this feature.",
            )
        readable = 0
        for b in browsers:
            profiles = enumerate_profiles(b)
            if profiles:
                readable += 1

        if readable == 0:
            return HealthReport(
                component_name="LocalBrowserData",
                status="warn",
                message="Browsers found, but profile data is not accessible.",
                detail="No readable profiles detected (possible permission issue or encrypted storage).",
                fix_suggestion="Ensure the application has read access to the browser's AppData directory.",
            )

        return HealthReport(
            component_name="LocalBrowserData",
            status="pass",
            message="Local browser data is available.",
            detail=f"Found {len(browsers)} browsers with {readable} readable profiles.",
        )
    except Exception as e:
        return HealthReport(
            component_name="LocalBrowserData",
            status="fail",
            message="Local browser data check failed.",
            detail=f"Failed to discover browsers: {e}",
            fix_suggestion="Check file permissions or OS constraints.",
        )


# Auto-register health check items
register_diagnostic(check_local_browser_health)


class LocalBrowserSearchInput(BaseModel):
    """Input schema for local browser data search tool."""

    keywords: list[str] = Field(
        default_factory=list,
        description="Search keywords (all must match). E.g. ['JIRA', 'company'].",
    )
    source: str = Field(
        default="both",
        description="Data source: 'bookmarks', 'history', or 'both'.",
    )
    since: str = Field(
        default="",
        description=(
            "Time window for history search. "
            "E.g. '1d' (1 day), '7d' (7 days), '3h' (3 hours). "
            "Empty for no time filter."
        ),
    )
    sort: str = Field(
        default="recent",
        description="Sort order for history: 'recent' or 'visits'.",
    )
    limit: int = Field(
        default=20,
        description="Max results per source. 0 for unlimited.",
        ge=0,
    )


def _parse_since(value: str) -> timedelta | None:
    """Parse time window string like '1d', '7d', '3h' into timedelta."""
    if not value:
        return None
    match = _SINCE_PATTERN.match(value.strip())
    if not match:
        return None
    amount = int(match.group(1))
    unit_key = match.group(2)
    unit_name = _SINCE_UNITS[unit_key]
    return timedelta(**{unit_name: amount})


def create_local_browser_data_tool() -> object:
    """Create the local browser data search tool.

    Returns:
        A LangChain tool function.
    """

    @tool("browser_local_search_tool", args_schema=LocalBrowserSearchInput)
    def browser_local_search(
        keywords: list[str] | None = None,
        source: str = "both",
        since: str = "",
        sort: str = "recent",
        limit: int = 20,
    ) -> str:
        """Search your local Chrome/Edge bookmarks and browsing history.

        Use this tool to find URLs from your browser that can't be found
        via web search — such as internal company systems, intranet pages,
        or previously visited articles you want to revisit.

        Examples:
        - Find internal JIRA: keywords=["JIRA", "company"]
        - Recent articles: keywords=["RAG"], since="7d", source="history"
        - Most visited sites this week: since="7d", sort="visits", source="history"
        """
        kw_list = keywords or []
        search_source = SearchSource(source) if source in ("bookmarks", "history", "both") else SearchSource.BOTH
        sort_order = SortOrder(sort) if sort in ("recent", "visits") else SortOrder.RECENT
        since_delta = _parse_since(since)

        do_bookmarks = search_source in (SearchSource.BOOKMARKS, SearchSource.BOTH)
        do_history = search_source in (SearchSource.HISTORY, SearchSource.BOTH)

        browsers = discover_browsers()
        if not browsers:
            return "No Chrome or Edge browser data found on this system."

        results = SearchResults()

        for browser in browsers:
            profiles = enumerate_profiles(browser)
            for profile in profiles:
                if do_bookmarks:
                    bm_results = search_bookmarks(browser.data_dir, profile, kw_list)
                    results.bookmarks.extend(bm_results)

                if do_history:
                    hist_results = search_history(
                        browser.data_dir,
                        profile,
                        kw_list,
                        since=since_delta,
                        sort=sort_order,
                        limit=limit * 2 if limit > 0 else 0,
                    )
                    results.history.extend(hist_results)

        # Cross-profile dedup and sort
        if sort_order == SortOrder.VISITS:
            results.history.sort(key=lambda h: (-h.visit_count, h.url))
        else:
            results.history.sort(key=lambda h: h.last_visit, reverse=True)

        if limit > 0:
            results.bookmarks = results.bookmarks[:limit]
            results.history = results.history[:limit]

        return results.format()

    return browser_local_search
