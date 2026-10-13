"""Wiki graph edge targets stored as concept identities.

[INPUT]
- sqlite3::Connection (POS: wiki index database)
- ..core.link_resolver::WikiLinkResolver, PageChange, link_lookup_forms (POS: link target to canonical concept key, spellings a target is matched on)

[OUTPUT]
- canonical_edge_target: resolve one extracted link target for storage
- store_edge: write one edge together with the spellings of its target
- relink_dangling_edges: re-resolve stored edge targets that name no indexed page

[POS]
Edges whose target resolves to a page are stored under that page's canonical key, so
the graph viewer, backlinks, insights and best-first expansion all follow the links
structural lint accepts. Targets that name no page keep their raw text. Every edge row
also carries the casefolded and sanitized spelling of its target (`target_key`,
`target_slug`, indexed), so a page that appears later finds the edges it can newly
resolve by lookup instead of re-resolving every unresolved edge in the index.
"""

from __future__ import annotations

import posixpath
import sqlite3
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING

from ..core.link_resolver import link_lookup_forms

if TYPE_CHECKING:
    from ..core.link_resolver import PageChange, WikiLinkResolver

# Stays far below SQLite's bound-parameter limit (each form is bound twice per query).
_FORMS_PER_QUERY = 200

_DANGLING_EDGES_SQL = """
    SELECT source, target, weight FROM wiki_edges
    WHERE target NOT LIKE 'system:%'
      AND target NOT IN (SELECT concept_name FROM wiki_index_meta)
"""


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


def store_edge(conn: sqlite3.Connection, source: str, target: str, weight: float) -> None:
    """Insert an edge with the spellings of its target; an existing edge keeps the larger weight."""
    target_key, target_slug = link_lookup_forms(target, source)
    conn.execute(
        """
        INSERT INTO wiki_edges (source, target, weight, target_key, target_slug) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source, target) DO UPDATE SET weight = MAX(weight, excluded.weight)
        """,
        (source, target, weight, target_key, target_slug),
    )


def relink_dangling_edges(
    conn: sqlite3.Connection,
    resolver: WikiLinkResolver,
    change: PageChange | None = None,
) -> int:
    """Rewrite edge targets that now resolve to a page; return the number of rewritten edges.

    A link may be written before its target page exists (compile order) or under a
    spelling that only a later page alias explains; this converges stored edges once
    the page is known. ``change`` narrows the work to edges spelled like the written
    page; without it (or after the resolver re-read the vault) every unresolved edge is
    re-resolved. Pseudo targets (`system:*`) are never touched.
    """
    rewritten = 0
    for source, old_target, weight in _unresolved_edges(conn, change):
        new_target = resolver.resolve(old_target, source)
        if new_target is None or new_target == old_target:
            continue
        conn.execute("DELETE FROM wiki_edges WHERE source = ? AND target = ?", (source, old_target))
        if new_target != source:
            store_edge(conn, source, new_target, weight)
        rewritten += 1
    return rewritten


def _unresolved_edges(conn: sqlite3.Connection, change: PageChange | None) -> list[tuple[str, str, float]]:
    if change is None or change.full_rescan:
        rows = conn.execute(_DANGLING_EDGES_SQL).fetchall()
        return [(str(r["source"]), str(r["target"]), float(r["weight"] or 1.0)) for r in rows]

    edges: dict[tuple[str, str], float] = {}
    for forms in _chunks(sorted(change.forms), _FORMS_PER_QUERY):
        marks = ",".join("?" * len(forms))
        rows = conn.execute(
            f"{_DANGLING_EDGES_SQL} AND (target_key IN ({marks}) OR target_slug IN ({marks}))",
            (*forms, *forms),
        ).fetchall()
        for row in rows:
            edges[(str(row["source"]), str(row["target"]))] = float(row["weight"] or 1.0)
    return [(source, target, weight) for (source, target), weight in edges.items()]


def _chunks(items: Sequence[str], size: int) -> Iterator[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
