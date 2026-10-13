"""One-time wiki index migration: one index identity per concept page.

[INPUT]
- sqlite3::Connection (POS: wiki index database)
- ..core.link_resolver::concept_index_key, WikiLinkResolver (POS: concept identity and link resolution)
- ..core.structure::WikiStructure (POS: vault paths)
- .edge_links::relink_dangling_edges (POS: edge target convergence)

[OUTPUT]
- CONCEPT_KEY_SCHEMA_VERSION: `PRAGMA user_version` stamped once the index is migrated
- migrate_concept_identity: merge rows indexed under a non-canonical spelling

[POS]
An index may hold one page twice (compile name vs. on-disk path). The migration renames
each such row to the page's on-disk key, drops the duplicate when both exist, and
re-resolves edge targets. Rows without a backing page are left untouched. The index is
derived data: no article file is read for content or modified.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import TYPE_CHECKING

from ..core.link_resolver import concept_index_key
from .edge_links import relink_dangling_edges

if TYPE_CHECKING:
    from ..core.link_resolver import WikiLinkResolver
    from ..core.structure import WikiStructure

logger = logging.getLogger(__name__)

CONCEPT_KEY_SCHEMA_VERSION = 1

_CONCEPT_TABLES = ("wiki_fts", "wiki_index_meta")


def migrate_concept_identity(
    conn: sqlite3.Connection,
    structure: WikiStructure,
    resolver: WikiLinkResolver,
) -> None:
    """Migrate the main index once; later opens only read ``PRAGMA user_version``."""
    version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    if version >= CONCEPT_KEY_SCHEMA_VERSION:
        return

    names = [str(row["concept_name"]) for row in conn.execute("SELECT concept_name FROM wiki_index_meta")]
    renamed = 0
    for name in names:
        key = concept_index_key(structure, name)
        if key != name:
            _rename_concept(conn, name, key)
            renamed += 1
    relinked = relink_dangling_edges(conn, resolver) if names else 0
    conn.execute("DELETE FROM wiki_edges WHERE source = target")
    conn.execute(f"PRAGMA user_version = {CONCEPT_KEY_SCHEMA_VERSION}")
    if renamed or relinked:
        logger.info("Wiki index identity migration: %d concepts renamed, %d edges relinked", renamed, relinked)


def _rename_concept(conn: sqlite3.Connection, old: str, new: str) -> None:
    for table in _CONCEPT_TABLES:
        if conn.execute(f"SELECT 1 FROM {table} WHERE concept_name = ?", (new,)).fetchone():
            conn.execute(f"DELETE FROM {table} WHERE concept_name = ?", (old,))
        else:
            conn.execute(f"UPDATE {table} SET concept_name = ? WHERE concept_name = ?", (new, old))
    conn.execute("UPDATE OR REPLACE wiki_edges SET source = ? WHERE source = ?", (new, old))
    conn.execute("UPDATE OR REPLACE wiki_edges SET target = ? WHERE target = ?", (new, old))
