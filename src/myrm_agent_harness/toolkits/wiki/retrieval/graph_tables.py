"""Federated wiki graph table access shared by the graph viewer and graph insights.

[INPUT]
- sqlite3::Connection (POS: wiki index connection with attached `pub_N` public databases)
- .sidecar_index::_SIDECAR_PREFIX (POS: directory sidecar index entry prefix)

[OUTPUT]
- federated_graph_queries: SQL selecting concept pages and edges across the local and public indexes

[POS]
Single definition of "which rows are graph nodes and edges", so the viewer, the insight
panel and community detection always analyze the same graph.
"""

from __future__ import annotations

import sqlite3

from .sidecar_index import _SIDECAR_PREFIX

_MAX_FEDERATED_DATABASES = 6
_INTERIM_RAW_PREFIX = "raw:"
_SIDECAR_ENTRY_PREFIX = f"{_SIDECAR_PREFIX}:"


def _concept_rows_filter() -> str:
    """Exclude interim raw-text and directory-sidecar entries: they are not concept pages."""
    return (
        f"substr(concept_name, 1, {len(_INTERIM_RAW_PREFIX)}) != '{_INTERIM_RAW_PREFIX}' "
        f"AND substr(concept_name, 1, {len(_SIDECAR_ENTRY_PREFIX)}) != '{_SIDECAR_ENTRY_PREFIX}'"
    )


def _attached_tables(conn: sqlite3.Connection, table: str) -> list[str]:
    tables = [table]
    attached = {str(row["name"]) for row in conn.execute("PRAGMA database_list").fetchall()}
    for idx in range(_MAX_FEDERATED_DATABASES):
        alias = f"pub_{idx}"
        if alias not in attached:
            continue
        try:
            found = conn.execute(
                f"SELECT 1 FROM {alias}.sqlite_master WHERE type IN ('table', 'view') AND name = ?",
                (table,),
            ).fetchone()
        except (sqlite3.OperationalError, sqlite3.DatabaseError):
            continue
        if found:
            tables.append(f"{alias}.{table}")
    return tables


def federated_graph_queries(conn: sqlite3.Connection) -> tuple[str, str]:
    """Return ``(concept_names_sql, edges_sql)`` over the local and attached public indexes.

    ``concept_names_sql`` yields distinct ``concept_name`` rows of concept pages;
    ``edges_sql`` yields ``source, target, weight`` rows (duplicates across databases
    are left to the caller to collapse).
    """
    row_filter = _concept_rows_filter()
    names_sql = " UNION ".join(
        f"SELECT concept_name FROM {table} WHERE {row_filter}" for table in _attached_tables(conn, "wiki_fts")
    )
    edges_sql = " UNION ALL ".join(
        f"SELECT source, target, weight FROM {table}" for table in _attached_tables(conn, "wiki_edges")
    )
    return names_sql, edges_sql
