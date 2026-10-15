"""Wiki graph edge weights, derived from the edges currently stored.

[INPUT]
- sqlite3::Connection (POS: wiki index database)

[OUTPUT]
- DIRECT_LINK_WEIGHT: weight of an edge whose ends share no link
- refresh_edge_weights: re-derive the weight of every edge that starts or ends at the given pages
- refresh_all_edge_weights: re-derive the weight of every edge in the index

[POS]
An edge weighs 3.0 for the link itself, plus 0.5 for each page both of its ends link to,
capped at 1.5 (Adamic-Adar style relatedness). The weight depends only on the two
out-link sets of the edge's ends, so it is a function of the stored edges, not of the order
pages were written in. A write that changes the out-links of page ``p`` re-derives exactly
the edges that start or end at ``p``; those are the only ones whose weight can differ. The
derivation reads the ``source`` and ``target`` columns only and never an earlier weight, so
re-running it is idempotent. Best-first expansion ranks neighbours by this weight; the graph
viewer and insights show it.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Collection

DIRECT_LINK_WEIGHT = 3.0
_SHARED_LINK_BONUS = 0.5
_MAX_SHARED_LINK_BONUS = 1.5

# Each page is bound twice per query, far below SQLite's bound-parameter limit.
_PAGES_PER_QUERY = 200

# The local table is named explicitly: federated public indexes are attached under other schemas.
_REFRESH_SQL = f"""
    UPDATE main.wiki_edges AS e
    SET weight = ROUND({DIRECT_LINK_WEIGHT} + MIN({_MAX_SHARED_LINK_BONUS}, {_SHARED_LINK_BONUS} * (
        SELECT COUNT(*)
        FROM main.wiki_edges AS src_out JOIN main.wiki_edges AS dst_out ON src_out.target = dst_out.target
        WHERE src_out.source = e.source AND dst_out.source = e.target
    )), 2)
"""


def refresh_edge_weights(conn: sqlite3.Connection, pages: Collection[str]) -> None:
    """Re-derive the weight of every edge that starts or ends at one of ``pages``."""
    ordered = sorted(set(pages))
    for start in range(0, len(ordered), _PAGES_PER_QUERY):
        chunk = ordered[start : start + _PAGES_PER_QUERY]
        marks = ",".join("?" * len(chunk))
        conn.execute(f"{_REFRESH_SQL} WHERE e.source IN ({marks}) OR e.target IN ({marks})", (*chunk, *chunk))


def refresh_all_edge_weights(conn: sqlite3.Connection) -> None:
    """Re-derive the weight of every edge in the index."""
    conn.execute(_REFRESH_SQL)
