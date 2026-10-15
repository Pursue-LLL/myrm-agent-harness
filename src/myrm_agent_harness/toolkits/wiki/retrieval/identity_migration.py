"""One-time wiki index migrations, versioned by `PRAGMA user_version`.

[INPUT]
- sqlite3::Connection (POS: wiki index database)
- ..core.link_resolver::concept_index_key, link_lookup_forms, WikiLinkResolver (POS: concept identity, link spellings and link resolution)
- ..core.structure::WikiStructure (POS: vault paths)
- .edge_links::relink_dangling_edges (POS: edge target convergence)
- .edge_weights::refresh_all_edge_weights (POS: edge weight derivation)

[OUTPUT]
- INDEX_SCHEMA_VERSION: `PRAGMA user_version` stamped once every step has run
- migrate_index_schema: run the pending steps in order

[POS]
Step 1 gives one index identity per concept page: an index may hold a page twice (compile
name vs. on-disk path), so each such row is renamed to the page's on-disk key and the
duplicate dropped when both exist; rows without a backing page are left untouched.
Step 2 records the spellings of every edge target and re-resolves all unresolved edges
under the current link rules (bare file names included). Step 3 derives every edge weight
from the stored edges, replacing weights that depended on the order pages were written in.
The index is derived data: no article file is read for content or modified.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING

from ..core.link_resolver import concept_index_key, link_lookup_forms
from .edge_links import relink_dangling_edges
from .edge_weights import refresh_all_edge_weights

if TYPE_CHECKING:
    from ..core.link_resolver import WikiLinkResolver
    from ..core.structure import WikiStructure

logger = logging.getLogger(__name__)

INDEX_SCHEMA_VERSION = 3

_CONCEPT_TABLES = ("wiki_fts", "wiki_index_meta")


def migrate_index_schema(
    conn: sqlite3.Connection,
    structure: WikiStructure,
    resolver: WikiLinkResolver,
) -> None:
    """Migrate the main index once; later opens only read ``PRAGMA user_version``."""
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version >= INDEX_SCHEMA_VERSION:
        return

    if version < 1:
        _merge_concept_identity(conn, structure)
    if version < 2:
        _converge_edges(conn, resolver)
    refresh_all_edge_weights(conn)
    conn.execute(f"PRAGMA user_version = {INDEX_SCHEMA_VERSION}")


def _merge_concept_identity(conn: sqlite3.Connection, structure: WikiStructure) -> None:
    names = [str(row["concept_name"]) for row in conn.execute("SELECT concept_name FROM wiki_index_meta")]
    renamed = 0
    for name in names:
        key = concept_index_key(structure, name)
        if key != name:
            _rename_concept(conn, name, key)
            renamed += 1
    if renamed:
        logger.info("Wiki index identity migration: %d concepts renamed", renamed)


def _converge_edges(conn: sqlite3.Connection, resolver: WikiLinkResolver) -> None:
    for row in conn.execute("SELECT source, target FROM wiki_edges").fetchall():
        source, target = str(row["source"]), str(row["target"])
        target_key, target_slug = link_lookup_forms(target, source)
        conn.execute(
            "UPDATE wiki_edges SET target_key = ?, target_slug = ? WHERE source = ? AND target = ?",
            (target_key, target_slug, source, target),
        )
    relinked = relink_dangling_edges(conn, resolver)
    conn.execute("DELETE FROM wiki_edges WHERE source = target")
    if relinked:
        logger.info("Wiki index edge migration: %d edges relinked", relinked)


def _rename_concept(conn: sqlite3.Connection, old: str, new: str) -> None:
    for table in _CONCEPT_TABLES:
        if conn.execute(f"SELECT 1 FROM {table} WHERE concept_name = ?", (new,)).fetchone():
            conn.execute(f"DELETE FROM {table} WHERE concept_name = ?", (old,))
        else:
            conn.execute(f"UPDATE {table} SET concept_name = ? WHERE concept_name = ?", (new, old))
    conn.execute("UPDATE OR REPLACE wiki_edges SET source = ? WHERE source = ?", (new, old))
    conn.execute("UPDATE OR REPLACE wiki_edges SET target = ? WHERE target = ?", (new, old))
