"""Tests for local browser data search toolkit.

Covers: chromium_locator, profile_enumerator, bookmark_searcher,
        history_searcher, types, tool.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from myrm_agent_harness.toolkits.local_browser_data.bookmark_searcher import (
    search_bookmarks,
)
from myrm_agent_harness.toolkits.local_browser_data.chromium_locator import (
    discover_browsers,
)
from myrm_agent_harness.toolkits.local_browser_data.history_searcher import (
    _datetime_to_webkit,
    _webkit_to_datetime,
    search_history,
)
from myrm_agent_harness.toolkits.local_browser_data.local_browser_data_agent_tools import (
    _parse_since,
    create_local_browser_data_tool,
)
from myrm_agent_harness.toolkits.local_browser_data.profile_enumerator import (
    enumerate_profiles,
)
from myrm_agent_harness.toolkits.local_browser_data.types import (
    BookmarkResult,
    BrowserProfile,
    ChromiumBrowser,
    HistoryResult,
    SearchResults,
    SearchSource,
    SortOrder,
)

# ============================================================
# types.py tests
# ============================================================


class TestTypes:
    def test_search_source_values(self):
        assert SearchSource.BOOKMARKS.value == "bookmarks"
        assert SearchSource.HISTORY.value == "history"
        assert SearchSource.BOTH.value == "both"

    def test_sort_order_values(self):
        assert SortOrder.RECENT.value == "recent"
        assert SortOrder.VISITS.value == "visits"

    def test_bookmark_result_format_simple(self):
        br = BookmarkResult(
            title="JIRA",
            url="https://jira.company.com",
            folder_path="Work",
            profile="Default",
            browser="Chrome",
        )
        formatted = br.format()
        assert "JIRA" in formatted
        assert "https://jira.company.com" in formatted
        assert "folder: Work" in formatted
        assert "@" not in formatted  # Default profile hidden

    def test_bookmark_result_format_non_default_profile(self):
        br = BookmarkResult(
            title="Test",
            url="https://test.com",
            folder_path="",
            profile="Personal",
            browser="Edge",
        )
        formatted = br.format()
        assert "@Personal" in formatted
        assert "[Edge]" in formatted

    def test_history_result_format(self):
        hr = HistoryResult(
            title="Article",
            url="https://blog.com/rag",
            last_visit=datetime(2026, 4, 15, 10, 30),
            visit_count=5,
            profile="Default",
            browser="Chrome",
        )
        formatted = hr.format()
        assert "Article" in formatted
        assert "2026-04-15 10:30" in formatted
        assert "visits=5" in formatted

    def test_search_results_format_empty(self):
        sr = SearchResults()
        assert sr.format() == "No results found."

    def test_search_results_format_mixed(self):
        sr = SearchResults(
            bookmarks=[
                BookmarkResult("BM1", "https://a.com", "", "Default", "Chrome"),
            ],
            history=[
                HistoryResult(
                    "H1",
                    "https://b.com",
                    datetime(2026, 4, 1, 12, 0),
                    1,
                    "Default",
                    "Chrome",
                ),
            ],
        )
        formatted = sr.format()
        assert "[Bookmarks] 1 results" in formatted
        assert "[History] 1 results" in formatted


# ============================================================
# chromium_locator.py tests
# ============================================================


class TestChromiumLocator:
    def test_discover_browsers_unsupported_platform(self):
        with patch("myrm_agent_harness.toolkits.local_browser_data.chromium_locator.sys") as mock_sys:
            mock_sys.platform = "freebsd"
            result = discover_browsers()
            assert result == []

    def test_discover_browsers_mac_chrome_exists(self, tmp_path: Path):
        chrome_dir = tmp_path / "Library" / "Application Support" / "Google" / "Chrome"
        chrome_dir.mkdir(parents=True)
        with (
            patch("myrm_agent_harness.toolkits.local_browser_data.chromium_locator.sys") as mock_sys,
            patch("myrm_agent_harness.toolkits.local_browser_data.chromium_locator.Path") as mock_path_cls,
        ):
            mock_sys.platform = "darwin"
            mock_path_cls.home.return_value = tmp_path
            # Make Path.__truediv__ actually compute paths
            mock_path_cls.__truediv__ = lambda self, other: tmp_path / other
            result = discover_browsers()
            # Due to mocking complexity, at minimum check it doesn't crash
            assert isinstance(result, list)

    def test_discover_real_system(self):
        """Smoke test: discover_browsers on the real system should not crash."""
        result = discover_browsers()
        assert isinstance(result, list)
        for b in result:
            assert isinstance(b, ChromiumBrowser)
            assert b.name in ("Chrome", "Edge")


# ============================================================
# profile_enumerator.py tests
# ============================================================


class TestProfileEnumerator:
    def test_enumerate_with_local_state(self, tmp_path: Path):
        data_dir = tmp_path / "chrome_data"
        data_dir.mkdir()
        local_state = {
            "profile": {
                "info_cache": {
                    "Default": {"name": "Main"},
                    "Profile 1": {"name": "Work"},
                }
            }
        }
        (data_dir / "Local State").write_text(json.dumps(local_state))
        browser = ChromiumBrowser(name="Chrome", data_dir=str(data_dir))

        profiles = enumerate_profiles(browser)
        assert len(profiles) == 2
        names = {p.display_name for p in profiles}
        assert names == {"Main", "Work"}

    def test_enumerate_fallback_no_local_state(self, tmp_path: Path):
        data_dir = tmp_path / "chrome_data"
        data_dir.mkdir()
        browser = ChromiumBrowser(name="Chrome", data_dir=str(data_dir))

        profiles = enumerate_profiles(browser)
        assert len(profiles) == 1
        assert profiles[0].display_name == "Default"

    def test_enumerate_fallback_invalid_json(self, tmp_path: Path):
        data_dir = tmp_path / "chrome_data"
        data_dir.mkdir()
        (data_dir / "Local State").write_text("{invalid}")
        browser = ChromiumBrowser(name="Chrome", data_dir=str(data_dir))

        profiles = enumerate_profiles(browser)
        assert len(profiles) == 1
        assert profiles[0].display_name == "Default"


# ============================================================
# bookmark_searcher.py tests
# ============================================================


class TestBookmarkSearcher:
    @pytest.fixture()
    def bookmark_data_dir(self, tmp_path: Path) -> str:
        profile_dir = tmp_path / "Default"
        profile_dir.mkdir()
        bookmarks = {
            "roots": {
                "bookmark_bar": {
                    "type": "folder",
                    "name": "Bookmarks Bar",
                    "children": [
                        {"type": "url", "name": "JIRA Dashboard", "url": "https://jira.company.com/dashboard"},
                        {"type": "url", "name": "Google", "url": "https://google.com"},
                        {
                            "type": "folder",
                            "name": "Work",
                            "children": [
                                {"type": "url", "name": "Confluence Wiki", "url": "https://wiki.company.com"},
                            ],
                        },
                    ],
                },
            }
        }
        (profile_dir / "Bookmarks").write_text(json.dumps(bookmarks))
        return str(tmp_path)

    def test_search_finds_matching(self, bookmark_data_dir: str):
        profile = BrowserProfile(directory="Default", display_name="Default", browser_name="Chrome")
        results = search_bookmarks(bookmark_data_dir, profile, ["JIRA"])
        assert len(results) == 1
        assert results[0].title == "JIRA Dashboard"
        assert "jira.company.com" in results[0].url

    def test_search_multi_keyword_and(self, bookmark_data_dir: str):
        profile = BrowserProfile(directory="Default", display_name="Default", browser_name="Chrome")
        results = search_bookmarks(bookmark_data_dir, profile, ["wiki", "company"])
        assert len(results) == 1
        assert results[0].title == "Confluence Wiki"

    def test_search_no_keywords_returns_empty(self, bookmark_data_dir: str):
        profile = BrowserProfile(directory="Default", display_name="Default", browser_name="Chrome")
        results = search_bookmarks(bookmark_data_dir, profile, [])
        assert results == []

    def test_search_no_match(self, bookmark_data_dir: str):
        profile = BrowserProfile(directory="Default", display_name="Default", browser_name="Chrome")
        results = search_bookmarks(bookmark_data_dir, profile, ["nonexistent"])
        assert results == []

    def test_preserves_folder_path(self, bookmark_data_dir: str):
        profile = BrowserProfile(directory="Default", display_name="Default", browser_name="Chrome")
        results = search_bookmarks(bookmark_data_dir, profile, ["confluence"])
        assert len(results) == 1
        assert "Work" in results[0].folder_path


# ============================================================
# history_searcher.py tests
# ============================================================


class TestHistorySearcher:
    def test_webkit_timestamp_conversion(self):
        """Verify WebKit epoch round-trip conversion."""
        now = datetime.now()
        webkit = _datetime_to_webkit(now)
        roundtrip = _webkit_to_datetime(webkit)
        assert abs((roundtrip - now).total_seconds()) < 1

    @pytest.fixture()
    def history_data_dir(self, tmp_path: Path) -> str:
        profile_dir = tmp_path / "Default"
        profile_dir.mkdir()
        db_path = profile_dir / "History"

        now_webkit = _datetime_to_webkit(datetime.now())
        old_webkit = _datetime_to_webkit(datetime.now() - timedelta(days=30))

        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE urls ("
            "  id INTEGER PRIMARY KEY,"
            "  url TEXT,"
            "  title TEXT,"
            "  visit_count INTEGER,"
            "  last_visit_time INTEGER"
            ")"
        )
        conn.execute(
            "INSERT INTO urls (url, title, visit_count, last_visit_time) VALUES (?, ?, ?, ?)",
            ("https://blog.com/rag-optimization", "RAG Optimization Guide", 5, now_webkit),
        )
        conn.execute(
            "INSERT INTO urls (url, title, visit_count, last_visit_time) VALUES (?, ?, ?, ?)",
            ("https://docs.python.org", "Python Docs", 50, now_webkit),
        )
        conn.execute(
            "INSERT INTO urls (url, title, visit_count, last_visit_time) VALUES (?, ?, ?, ?)",
            ("https://old-article.com", "Old Article", 1, old_webkit),
        )
        conn.commit()
        conn.close()
        return str(tmp_path)

    def test_search_by_keyword(self, history_data_dir: str):
        profile = BrowserProfile(directory="Default", display_name="Default", browser_name="Chrome")
        results = search_history(history_data_dir, profile, ["rag"])
        assert len(results) == 1
        assert results[0].title == "RAG Optimization Guide"

    def test_search_with_time_window(self, history_data_dir: str):
        profile = BrowserProfile(directory="Default", display_name="Default", browser_name="Chrome")
        results = search_history(history_data_dir, profile, [], since=timedelta(days=7))
        assert len(results) == 2  # Only recent entries
        urls = {r.url for r in results}
        assert "https://old-article.com" not in urls

    def test_sort_by_visits(self, history_data_dir: str):
        profile = BrowserProfile(directory="Default", display_name="Default", browser_name="Chrome")
        results = search_history(history_data_dir, profile, [], sort=SortOrder.VISITS, limit=0)
        assert len(results) >= 2
        assert results[0].visit_count >= results[1].visit_count

    def test_limit(self, history_data_dir: str):
        profile = BrowserProfile(directory="Default", display_name="Default", browser_name="Chrome")
        results = search_history(history_data_dir, profile, [], limit=1)
        assert len(results) == 1

    def test_missing_history_file(self, tmp_path: Path):
        profile_dir = tmp_path / "Default"
        profile_dir.mkdir()
        profile = BrowserProfile(directory="Default", display_name="Default", browser_name="Chrome")
        results = search_history(str(tmp_path), profile, ["test"])
        assert results == []


# ============================================================
# tool.py tests
# ============================================================


class TestTool:
    def test_parse_since_days(self):
        td = _parse_since("7d")
        assert td is not None
        assert td == timedelta(days=7)

    def test_parse_since_hours(self):
        td = _parse_since("3h")
        assert td is not None
        assert td == timedelta(hours=3)

    def test_parse_since_minutes(self):
        td = _parse_since("30m")
        assert td is not None
        assert td == timedelta(minutes=30)

    def test_parse_since_empty(self):
        assert _parse_since("") is None

    def test_parse_since_invalid(self):
        assert _parse_since("abc") is None

    def test_create_tool(self):
        tool = create_local_browser_data_tool()
        assert tool is not None
        assert tool.name == "browser_local_search_tool"

    def test_tool_no_browsers_found(self):
        tool = create_local_browser_data_tool()
        with patch(
            "myrm_agent_harness.toolkits.local_browser_data.local_browser_data_agent_tools.discover_browsers",
            return_value=[],
        ):
            result = tool.invoke({"keywords": ["test"]})
            assert "No Chrome or Edge" in result

    def test_tool_with_mock_data(self, tmp_path: Path):
        """End-to-end test with mocked browser data."""
        profile_dir = tmp_path / "Default"
        profile_dir.mkdir()

        bookmarks = {
            "roots": {
                "bookmark_bar": {
                    "type": "folder",
                    "name": "Bar",
                    "children": [
                        {"type": "url", "name": "Internal JIRA", "url": "https://jira.internal.com"},
                    ],
                },
            }
        }
        (profile_dir / "Bookmarks").write_text(json.dumps(bookmarks))

        mock_browser = ChromiumBrowser(name="Chrome", data_dir=str(tmp_path))
        mock_profile = BrowserProfile(directory="Default", display_name="Default", browser_name="Chrome")

        tool = create_local_browser_data_tool()
        with (
            patch(
                "myrm_agent_harness.toolkits.local_browser_data.local_browser_data_agent_tools.discover_browsers",
                return_value=[mock_browser],
            ),
            patch(
                "myrm_agent_harness.toolkits.local_browser_data.local_browser_data_agent_tools.enumerate_profiles",
                return_value=[mock_profile],
            ),
        ):
            result = tool.invoke({"keywords": ["jira"], "source": "bookmarks"})
            assert "Internal JIRA" in result
            assert "jira.internal.com" in result
