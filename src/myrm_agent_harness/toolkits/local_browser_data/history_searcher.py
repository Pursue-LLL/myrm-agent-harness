"""Chromium browsing history SQLite search.


[INPUT]
- types::BrowserProfile (POS: browser profile info)
- types::HistoryResult (POS: history search result)
- types::SortOrder (POS: sort order enum)

[OUTPUT]
- search_history: search browsing history in specified profile

[POS]
Chromium browsing history searcher. Copies History SQLite to temp directory to avoid browser write-lock
conflicts; supports time window filtering, multi-keyword AND matching, and sorting by recent visit/visit count.
Handles WebKit timestamp format (1601-01-01 microsecond offset).
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from .types import BrowserProfile, HistoryResult, SortOrder

logger = logging.getLogger(__name__)

# WebKit epoch: 1601-01-01 00:00:00 UTC, stored as microseconds.
# Offset from Unix epoch (1970-01-01) in microseconds.
_WEBKIT_EPOCH_OFFSET_US = 11_644_473_600_000_000


def _webkit_to_datetime(webkit_us: int) -> datetime:
    """Convert WebKit timestamp (microseconds since 1601-01-01) to datetime."""
    unix_us = webkit_us - _WEBKIT_EPOCH_OFFSET_US
    return datetime.fromtimestamp(unix_us / 1_000_000)


def _datetime_to_webkit(dt: datetime) -> int:
    """Convert datetime to WebKit timestamp."""
    unix_us = int(dt.timestamp() * 1_000_000)
    return unix_us + _WEBKIT_EPOCH_OFFSET_US


def search_history(
    browser_data_dir: str,
    profile: BrowserProfile,
    keywords: Sequence[str],
    *,
    since: timedelta | None = None,
    sort: SortOrder = SortOrder.RECENT,
    limit: int = 20,
) -> list[HistoryResult]:
    """Search browsing history in a Chromium profile.

    Copies the History SQLite database to a temp file before querying
    to avoid locking conflicts with the running browser.

    Args:
        browser_data_dir: Browser data directory path.
        profile: Browser profile to search.
        keywords: Search keywords (all must match title or URL).
        since: Time window filter (e.g. ``timedelta(days=7)``).
        sort: Sort order — by most recent visit or by visit count.
        limit: Maximum number of results. 0 for unlimited.

    Returns:
        Matching history results, sorted as specified.
    """
    history_path = Path(browser_data_dir) / profile.directory / "History"
    if not history_path.is_file():
        return []

    tmp_path = _copy_to_temp(history_path)
    if tmp_path is None:
        return []

    try:
        return _query_history(tmp_path, profile, keywords, since=since, sort=sort, limit=limit)
    finally:
        _cleanup_temp(tmp_path)


def _copy_to_temp(src: Path) -> Path | None:
    """Copy History SQLite to temp directory to avoid browser lock."""
    try:
        fd, tmp = tempfile.mkstemp(suffix=".sqlite", prefix="chrome-history-")
        os.close(fd)
        shutil.copy2(str(src), tmp)
        return Path(tmp)
    except OSError as exc:
        logger.warning("Failed to copy History file: %s", exc)
        return None


def _cleanup_temp(path: Path) -> None:
    """Remove temp copy."""
    with contextlib.suppress(OSError):
        path.unlink(missing_ok=True)


def _query_history(
    db_path: Path,
    profile: BrowserProfile,
    keywords: Sequence[str],
    *,
    since: timedelta | None,
    sort: SortOrder,
    limit: int,
) -> list[HistoryResult]:
    """Execute SQLite query against copied History database."""
    conditions = ["last_visit_time > 0"]
    params: list[str] = []

    for kw in keywords:
        conditions.append("(LOWER(title || ' ' || url) LIKE ?)")
        params.append(f"%{kw.lower()}%")

    if since is not None:
        cutoff = datetime.now() - since
        webkit_cutoff = _datetime_to_webkit(cutoff)
        conditions.append("last_visit_time >= ?")
        params.append(str(webkit_cutoff))

    order_by = "visit_count DESC, last_visit_time DESC" if sort == SortOrder.VISITS else "last_visit_time DESC"
    limit_clause = limit if limit > 0 else -1

    sql = (
        f"SELECT title, url, last_visit_time, visit_count "
        f"FROM urls WHERE {' AND '.join(conditions)} "
        f"ORDER BY {order_by} LIMIT {limit_clause}"
    )

    try:
        conn = sqlite3.connect(str(db_path), timeout=5)
        try:
            cursor = conn.execute(sql, params)
            rows = cursor.fetchall()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        logger.warning(
            "SQLite query failed for %s/%s: %s",
            profile.browser_name,
            profile.display_name,
            exc,
        )
        return []

    results: list[HistoryResult] = []
    for title, url, last_visit_time, visit_count in rows:
        try:
            last_visit = _webkit_to_datetime(last_visit_time)
        except (ValueError, OSError):
            continue
        results.append(
            HistoryResult(
                title=title or "",
                url=url or "",
                last_visit=last_visit,
                visit_count=visit_count or 0,
                profile=profile.display_name,
                browser=profile.browser_name,
            )
        )

    return results
