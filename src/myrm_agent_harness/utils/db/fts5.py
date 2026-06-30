"""FTS5 Utilities

Provides robust sanitization for SQLite FTS5 MATCH queries and silent
auto-healing for corrupted FTS5 indexes (power-loss survival guard).

[INPUT]
- sqlite3.Connection (POS: open connection for integrity/rebuild operations)
- str (POS: table name, query string)

[OUTPUT]
- sanitize_fts5_query: Sanitize user input for safe use in FTS5 MATCH queries.
- fts5_integrity_check: Check FTS5 virtual table health via official command.
- fts5_rebuild: Rebuild a corrupted FTS5 index (safe, data-preserving).
- fts5_auto_heal: Detect corruption on query failure and rebuild transparently.

[POS]
Leaf FTS5 utility module in the unified SQLite hardening factory. Extends the
file-level guards in ``sqlite/integrity.py`` to cover FTS5 virtual table indexes.
"""

from __future__ import annotations

import logging
import re
import sqlite3

logger = logging.getLogger(__name__)


def sanitize_fts5_query(query: str) -> str:
    """Sanitize user input for safe use in FTS5 MATCH queries.

    FTS5 has its own query syntax where characters like `+`, `*`, `(`, `)`,
    `{`, `}`, `"`, `^` and bare boolean operators (`AND`, `OR`, `NOT`) have
    special meaning. Passing raw user input directly to MATCH can cause
    `sqlite3.OperationalError`.

    Strategy:
    - Preserve properly paired quoted phrases (`"exact phrase"`)
    - Strip unmatched FTS5-special characters that would cause errors
    - Wrap unquoted hyphenated and dotted terms in quotes so FTS5
      matches them as exact phrases instead of splitting on the
      hyphen/dot (e.g. `chat-send`, `P2.2`, `my-app.config.ts`)
    """
    if not query:
        return ""

    # Step 0: Strip NULL bytes and control characters that crash FTS5
    query = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", query)

    # Step 1: Extract balanced double-quoted phrases and protect them
    _quoted_parts: list[str] = []

    def _preserve_quoted(m: re.Match) -> str:
        _quoted_parts.append(m.group(0))
        return f"\x00Q{len(_quoted_parts) - 1}\x00"

    sanitized = re.sub(r'"[^"]*"', _preserve_quoted, query)

    # Step 2: Strip remaining (unmatched) FTS5-special characters
    sanitized = re.sub(r"[+{}()\"\^<>/\\:~#@!$%&=?;,\[\]|]", " ", sanitized)

    # Step 3: Collapse repeated * (e.g. "***") into a single one,
    # and remove leading * (prefix-only needs at least one char before *)
    sanitized = re.sub(r"\*+", "*", sanitized)
    sanitized = re.sub(r"(^|\s)\*", r"\1", sanitized)

    # Step 4: Remove dangling boolean operators at start/end that would
    # cause syntax errors (e.g. "hello AND" or "OR world").
    # Loop until stable to handle "AND OR NOT" -> "OR NOT" -> "NOT" -> "".
    prev = None
    while sanitized != prev:
        prev = sanitized
        sanitized = re.sub(r"(?i)^(AND|OR|NOT)\b\s*", "", sanitized.strip())
        sanitized = re.sub(r"(?i)\s+(AND|OR|NOT)\s*$", "", sanitized.strip())

    # Step 5: Wrap unquoted dotted and/or hyphenated terms in double
    # quotes. FTS5's tokenizer splits on dots and hyphens, turning
    # `chat-send` into `chat AND send` and `P2.2` into `p2 AND 2`.
    # Quoting preserves phrase semantics.
    sanitized = re.sub(r"\b(\w+(?:[.-]\w+)+)\b", r'"\1"', sanitized)

    # Step 5b: Remove hyphens outside of quoted compound terms.
    # FTS5 treats `-word` as column selector → error. Also strip
    # standalone dashes (e.g. `---`, `hello---world`).
    # Protect Step-5 quoted phrases first, then clean unquoted hyphens.
    _step5_quotes: list[str] = []

    def _protect_step5(m: re.Match) -> str:
        _step5_quotes.append(m.group(0))
        return f"\x01P{len(_step5_quotes) - 1}\x01"

    sanitized = re.sub(r'"[^"]*"', _protect_step5, sanitized)
    sanitized = re.sub(r"-+", " ", sanitized)
    for i, q in enumerate(_step5_quotes):
        sanitized = sanitized.replace(f"\x01P{i}\x01", q)

    # Step 5c: Remove NEAR operator when used outside quotes
    sanitized = re.sub(r"\bNEAR\b", " ", sanitized)

    # Step 6: Restore preserved quoted phrases
    for i, quoted in enumerate(_quoted_parts):
        sanitized = sanitized.replace(f"\x00Q{i}\x00", quoted)

    return sanitized.strip()


# ---------------------------------------------------------------------------
# FTS5 Index Integrity & Auto-Heal
# ---------------------------------------------------------------------------


_VALID_TABLE_RE = re.compile(r"^[a-zA-Z_]\w*$")


def _validate_table_name(table: str) -> str:
    """Guard against SQL injection in table name parameters."""
    if not _VALID_TABLE_RE.match(table):
        raise ValueError(f"Invalid FTS5 table name: {table!r}")
    return table


def fts5_integrity_check(conn: sqlite3.Connection, table: str) -> bool:
    """Return True if the FTS5 virtual table index is healthy.

    Uses the official FTS5 ``integrity-check`` command. Returns False when the
    shadow tables are inconsistent (e.g. after unclean shutdown with un-flushed
    WAL pages).
    """
    table = _validate_table_name(table)
    try:
        conn.execute(f"INSERT INTO {table}({table}) VALUES('integrity-check')")
        return True
    except sqlite3.OperationalError:
        return False


def fts5_rebuild(conn: sqlite3.Connection, table: str) -> None:
    """Rebuild the FTS5 index from source data (safe, data-preserving).

    The ``rebuild`` command re-reads all content and reconstructs the inverted
    index from scratch. No user data is lost — only the index is regenerated.
    Typical cost: <100 ms for tables with <10 000 rows.
    """
    table = _validate_table_name(table)
    conn.execute(f"INSERT INTO {table}({table}) VALUES('rebuild')")
    logger.info("FTS5 index rebuilt successfully: %s", table)


def fts5_auto_heal(conn: sqlite3.Connection, table: str) -> bool:
    """Attempt to heal a corrupted FTS5 index after a query failure.

    Call this from an ``except sqlite3.OperationalError`` block. It runs
    ``integrity-check`` to confirm corruption, then ``rebuild`` to fix it.
    Returns True if the index was repaired, False if repair failed or was
    unnecessary.
    """
    try:
        if fts5_integrity_check(conn, table):
            return False
        fts5_rebuild(conn, table)
        return fts5_integrity_check(conn, table)
    except sqlite3.Error as exc:
        logger.error("FTS5 auto-heal failed for %s: %s", table, exc)
        return False
