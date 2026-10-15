"""Wiki graph edge targets stored as concept identities.

[INPUT]
- sqlite3::Connection (POS: wiki index database)
- ..core.link_resolver::WikiLinkResolver, PageChange, link_lookup_forms (POS: link target to canonical concept key, spellings a target is matched on)
- .edge_weights::DIRECT_LINK_WEIGHT, refresh_edge_weights (POS: edge weight derivation)

[OUTPUT]
- canonical_edge_target: resolve one extracted link target for storage
- store_edge: write one edge together with the spellings of its target
- relink_dangling_edges: re-resolve stored edge targets that name no indexed page, then re-derive the weights of the pages whose links changed
- linkers_to_reread: pages whose links must be re-read because a same-named page appeared or went away

[POS]
Edges whose target resolves to a page are stored under that page's canonical key, so
the graph viewer, backlinks, insights and best-first expansion all follow the links
structural lint accepts. Targets that name no page keep their raw text. Every edge row
also carries the casefolded and sanitized spelling of its target (`target_key`,
`target_slug`, indexed), so a page that appears later finds the edges it can newly
resolve by lookup instead of re-resolving every unresolved edge in the index. A resolved
edge does not keep the text it was written from, so links that a same-named page
makes ambiguous (or unambiguous) are found through the pages that linked to the
same-named pages and re-read from their own text.
"""

from __future__ import annotations

import posixpath
import sqlite3
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING

from ..core.link_resolver import link_lookup_forms
from .edge_weights import DIRECT_LINK_WEIGHT, refresh_edge_weights

if TYPE_CHECKING:
    from ..core.link_resolver import PageChange, WikiLinkResolver

# Stays far below SQLite's bound-parameter limit (each form is bound twice per query).
_FORMS_PER_QUERY = 200

_DANGLING_EDGES_SQL = """
    SELECT source, target FROM wiki_edges
    WHERE target NOT IN (SELECT concept_name FROM wiki_index_meta)
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


def store_edge(conn: sqlite3.Connection, source: str, target: str) -> None:
    """Insert an edge with the spellings of its target; an edge that already exists stays as it is.

    The edge starts at the direct-link weight; the caller re-derives the weights of the
    pages it changed once all their edges are stored (``refresh_edge_weights``).
    """
    target_key, target_slug = link_lookup_forms(target, source)
    conn.execute(
        """
        INSERT INTO wiki_edges (source, target, weight, target_key, target_slug) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source, target) DO NOTHING
        """,
        (source, target, DIRECT_LINK_WEIGHT, target_key, target_slug),
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
    re-resolved. The pages whose links were rewritten have their edge weights re-derived.
    """
    rewritten = 0
    relinked_sources: set[str] = set()
    for source, old_target in _unresolved_edges(conn, change):
        new_target = resolver.resolve(old_target, source)
        if new_target is None or new_target == old_target:
            continue
        conn.execute("DELETE FROM wiki_edges WHERE source = ? AND target = ?", (source, old_target))
        if new_target != source:
            store_edge(conn, source, new_target)
        relinked_sources.add(source)
        rewritten += 1
    refresh_edge_weights(conn, relinked_sources)
    return rewritten


def linkers_to_reread(conn: sqlite3.Connection, page: str, change: PageChange, *, removed: bool) -> list[str]:
    """Pages whose links may read differently now that ``page`` appeared or disappeared.

    A stored edge keeps the page a link resolved to, not the text that was written, so a
    link that became ambiguous (a same-named page appeared) or unambiguous (one went away)
    can only be re-resolved from its own page. When a page went away, every page that
    linked to it is a candidate. When one appeared, only the pages that linked to a page
    sharing its path, title, alias or canonical id are: finding the links a mere
    namesake affects would mean re-reading every page that links to any page of that
    file name, which grows with the number of namesakes, so those edges are corrected
    when their page is next written.
    """
    if removed:
        linkers = set(_linkers(conn, page)) if change.colliding or change.namesakes else set()
    else:
        linkers = {source for other in change.colliding for source in _linkers(conn, other)}
    linkers.discard(page)
    return sorted(linkers)


def _linkers(conn: sqlite3.Connection, target: str) -> list[str]:
    rows = conn.execute("SELECT DISTINCT source FROM wiki_edges WHERE target = ?", (target,)).fetchall()
    return [str(row["source"]) for row in rows]


def _unresolved_edges(conn: sqlite3.Connection, change: PageChange | None) -> list[tuple[str, str]]:
    if change is None or change.full_rescan:
        rows = conn.execute(_DANGLING_EDGES_SQL).fetchall()
        return [(str(r["source"]), str(r["target"])) for r in rows]

    edges: set[tuple[str, str]] = set()
    for forms in _chunks(sorted(change.forms), _FORMS_PER_QUERY):
        marks = ",".join("?" * len(forms))
        rows = conn.execute(
            f"{_DANGLING_EDGES_SQL} AND (target_key IN ({marks}) OR target_slug IN ({marks}))",
            (*forms, *forms),
        ).fetchall()
        edges.update((str(row["source"]), str(row["target"])) for row in rows)
    return sorted(edges)


def _chunks(items: Sequence[str], size: int) -> Iterator[Sequence[str]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]
