"""Wiki graph edge targets stored as concept identities.

[INPUT]
- sqlite3::Connection (POS: wiki index database)
- ..core.link_resolver::WikiLinkResolver (POS: link target to canonical concept key)

[OUTPUT]
- canonical_edge_target: resolve one extracted link target for storage
- relink_dangling_edges: re-resolve stored edge targets that name no indexed page

[POS]
Edges whose target resolves to a page are stored under that page's canonical key, so
the graph viewer, backlinks, insights and best-first expansion all follow the same
links that structural lint accepts. Targets that name no page keep their raw text.
"""

from __future__ import annotations

import posixpath
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.link_resolver import WikiLinkResolver


def canonical_edge_target(
    resolver: WikiLinkResolver,
    source: str,
    target: str,
    *,
    relative_to_source: bool = False,
) -> str:
    """Return the canonical concept key ``target`` points at, or ``target`` unchanged.

    ``relative_to_source`` applies markdown-link semantics: the target is first tried
    relative to the linking page's directory.
    """
    if relative_to_source:
        joined = posixpath.normpath(posixpath.join(posixpath.dirname(source), target))
        resolved = resolver.resolve(joined)
        if resolved is not None:
            return resolved
    resolved = resolver.resolve(target, source)
    return resolved if resolved is not None else target


def relink_dangling_edges(conn: sqlite3.Connection, resolver: WikiLinkResolver) -> int:
    """Rewrite edge targets that now resolve to a page; return the number of rewritten edges.

    A link may be written before its target page exists (compile order) or under a
    spelling that only a later page alias explains; this converges stored edges once
    the page is known. Pseudo targets (`system:*`) are never touched.
    """
    rows = conn.execute(
        """
        SELECT source, target, weight FROM wiki_edges
        WHERE target NOT LIKE 'system:%'
          AND target NOT IN (SELECT concept_name FROM wiki_index_meta)
        """
    ).fetchall()

    rewritten = 0
    for row in rows:
        source, old_target, weight = str(row["source"]), str(row["target"]), float(row["weight"] or 1.0)
        new_target = resolver.resolve(old_target, source)
        if new_target is None or new_target == old_target:
            continue
        conn.execute("DELETE FROM wiki_edges WHERE source = ? AND target = ?", (source, old_target))
        if new_target != source:
            conn.execute(
                """
                INSERT INTO wiki_edges (source, target, weight) VALUES (?, ?, ?)
                ON CONFLICT(source, target) DO UPDATE SET weight = MAX(weight, excluded.weight)
                """,
                (source, new_target, weight),
            )
        rewritten += 1
    return rewritten
