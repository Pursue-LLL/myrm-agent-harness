"""Exact Fact Relational & FTS5 Storage Handler.

Encapsulates zero-loss SQLite storage and inverted search for exact facts
(UUIDs, Git SHAs, SemVer tags, network endpoints, system configuration keys).

[INPUT]
- aiosqlite.Connection: active SQLite connection
- str: raw text content, query string, or memory identifiers

[OUTPUT]
- init_exact_fact_tables: idempotent table creation + FTS5 probe
- save_exact_fact: upsert exact fact identifiers and FTS5 doc
- search_exact_facts: deterministic hybrid search returning MemorySearchResult
- delete_exact_fact: cleanup identifiers and FTS5 entries on memory deletion

[POS]
Harness internal storage worker under relational/. Decoupled from service layer.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, UTC
from uuid import uuid4

import aiosqlite

from myrm_agent_harness.toolkits.memory.strategies.exact_fact import (
    ExactFactClassifier,
)
from myrm_agent_harness.toolkits.memory.types import (
    BaseMemory,
    MemoryScope,
    MemorySearchResult,
    MemoryType,
)
from myrm_agent_harness.utils.db.fts5 import sanitize_fts5_query

logger = logging.getLogger(__name__)


async def init_exact_fact_tables(conn: aiosqlite.Connection) -> bool:
    """Initialize exact fact relational tables and probe for FTS5 availability."""
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS exact_fact_identifiers (
            id TEXT PRIMARY KEY,
            memory_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            identifier TEXT NOT NULL,
            identifier_type TEXT NOT NULL,
            content TEXT NOT NULL DEFAULT '',
            primary_namespace TEXT NOT NULL DEFAULT '',
            namespaces TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    for idx_sql in (
        "CREATE INDEX IF NOT EXISTS idx_exact_fact_id_val ON exact_fact_identifiers(identifier)",
        "CREATE INDEX IF NOT EXISTS idx_exact_fact_id_user ON exact_fact_identifiers(user_id, identifier)",
        "CREATE INDEX IF NOT EXISTS idx_exact_fact_id_mem ON exact_fact_identifiers(memory_id)",
        "CREATE INDEX IF NOT EXISTS idx_exact_fact_id_scope ON exact_fact_identifiers(primary_namespace)",
    ):
        await conn.execute(idx_sql)

    # Probe FTS5 virtual table availability safely
    fts5_supported = False
    try:
        await conn.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS exact_facts_fts USING fts5(
                memory_id UNINDEXED,
                user_id UNINDEXED,
                content,
                identifiers,
                tokenize='unicode61'
            )
            """
        )
        fts5_supported = True
    except Exception as fts_err:
        logger.warning(
            "SQLite FTS5 virtual table unavailable: %s. Exact facts will use relational B-Tree index.",
            fts_err,
        )
        fts5_supported = False

    return fts5_supported


async def save_exact_fact(
    conn: aiosqlite.Connection,
    *,
    memory_id: str,
    user_id: str,
    content: str,
    identifiers: list[str],
    primary_namespace: str = "",
    namespaces: list[str] | None = None,
    fts5_supported: bool = True,
) -> None:
    """Upsert exact fact identifiers and update FTS5 virtual table."""
    now = datetime.now(UTC).isoformat()
    ns_json = json.dumps(namespaces or [])

    # Delete existing entries for this memory_id first to maintain consistency
    await conn.execute(
        "DELETE FROM exact_fact_identifiers WHERE memory_id = ?",
        (memory_id,),
    )

    for ident in identifiers:
        ident_clean = ident.strip()
        if not ident_clean:
            continue
        ident_type = "generic"
        if "-" in ident_clean and len(ident_clean) == 36:
            ident_type = "uuid"
        elif ident_clean.isupper() and "_" in ident_clean:
            ident_type = "config_key"
        elif ":" in ident_clean or ident_clean.isdigit():
            ident_type = "network"

        record_id = uuid4().hex
        await conn.execute(
            """
            INSERT INTO exact_fact_identifiers (
                id, memory_id, user_id, identifier, identifier_type,
                content, primary_namespace, namespaces, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record_id,
                memory_id,
                user_id,
                ident_clean,
                ident_type,
                content,
                primary_namespace,
                ns_json,
                now,
                now,
            ),
        )

    # Sync to FTS5 if supported
    if fts5_supported:
        try:
            await conn.execute(
                "DELETE FROM exact_facts_fts WHERE memory_id = ?",
                (memory_id,),
            )
            ident_joined = " ".join(identifiers)
            await conn.execute(
                "INSERT INTO exact_facts_fts (memory_id, user_id, content, identifiers) VALUES (?, ?, ?, ?)",
                (memory_id, user_id, content, ident_joined),
            )
        except Exception as fts_err:
            logger.warning("FTS5 sync error for exact fact %s: %s", memory_id, fts_err)


async def search_exact_facts(
    conn: aiosqlite.Connection,
    query: str,
    limit: int = 10,
    *,
    namespaces: list[str] | None = None,
    fts5_supported: bool = True,
) -> list[MemorySearchResult]:
    """Search exact facts using high-entropy token extraction and FTS5 inverted search."""
    if not query or not query.strip():
        return []

    results: list[MemorySearchResult] = []
    seen_memory_ids: set[str] = set()

    extracted = ExactFactClassifier.extract_identifiers(query)

    # 1. Deterministic B-Tree search by exact identifier
    if extracted:
        placeholders = ",".join("?" for _ in extracted)
        sql = f"""
            SELECT memory_id, user_id, content, primary_namespace, namespaces, identifier
            FROM exact_fact_identifiers
            WHERE identifier IN ({placeholders})
            LIMIT ?
        """
        params = [*extracted, limit]
        async with conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            for row in rows:
                mem_id, u_id, cnt, p_ns, ns_str, matched_ident = row
                if mem_id in seen_memory_ids:
                    continue
                seen_memory_ids.add(mem_id)
                ns_list = json.loads(ns_str) if ns_str else []
                mem = BaseMemory(
                    id=mem_id,
                    user_id=u_id,
                    content=cnt,
                    is_exact_fact=True,
                    exact_identifiers=extracted,
                    scope=MemoryScope(primary_namespace=p_ns, namespaces=ns_list),
                )
                results.append(
                    MemorySearchResult(
                        memory=mem,
                        score=1.0,  # Deterministic exact match gets highest score
                        memory_type=MemoryType.SEMANTIC,
                    )
                )

    # 2. FTS5 full-text inverted search if limit not reached and FTS5 enabled
    if fts5_supported and len(results) < limit:
        sanitized = sanitize_fts5_query(query)
        if sanitized:
            remaining = limit - len(results)
            try:
                fts_sql = """
                    SELECT memory_id, user_id, content, identifiers
                    FROM exact_facts_fts
                    WHERE exact_facts_fts MATCH ?
                    LIMIT ?
                """
                async with conn.execute(fts_sql, (sanitized, remaining)) as cursor:
                    rows = await cursor.fetchall()
                    for row in rows:
                        mem_id, u_id, cnt, idents_str = row
                        if mem_id in seen_memory_ids:
                            continue
                        seen_memory_ids.add(mem_id)
                        idents = idents_str.split() if idents_str else []
                        mem = BaseMemory(
                            id=mem_id,
                            user_id=u_id,
                            content=cnt,
                            is_exact_fact=True,
                            exact_identifiers=idents,
                        )
                        results.append(
                            MemorySearchResult(
                                memory=mem,
                                score=0.95,
                                memory_type=MemoryType.SEMANTIC,
                            )
                        )
            except Exception as fts_err:
                logger.debug("FTS5 match evaluation error for query '%s': %s", sanitized, fts_err)

    return results


async def delete_exact_fact(
    conn: aiosqlite.Connection,
    memory_id: str,
    *,
    fts5_supported: bool = True,
) -> None:
    """Remove exact fact records and virtual table documents."""
    await conn.execute(
        "DELETE FROM exact_fact_identifiers WHERE memory_id = ?",
        (memory_id,),
    )
    if fts5_supported:
        try:
            await conn.execute(
                "DELETE FROM exact_facts_fts WHERE memory_id = ?",
                (memory_id,),
            )
        except Exception as fts_err:
            logger.debug("FTS5 deletion error for %s: %s", memory_id, fts_err)
