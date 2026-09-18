"""Recursive CTE graph traversal operations for SQLite Graph Store.

[INPUT]
memory.graph.exceptions::GraphQueryError (POS: 图存储异常类)

[OUTPUT]
execute_causal_chain: 基于 CTE 递归遍历因果链并识别环路，自动过滤失效历史边
execute_related_nodes: 基于共享 target 发现兄弟协同关联节点
execute_related_nodes_with_depth: 基于 CTE 发现多跳关联节点并附带深度信息
execute_delete_subgraph: 级联删除节点及其连带边
execute_delete_all_by_owner: 按归属者 JSON 属性级联删除节点与关系

[POS]
SQLite 递归 CTE 图遍历执行器。封装高阶因果图分析、环路检测及批量级联操作。
"""

from __future__ import annotations

import logging

import aiosqlite

from myrm_agent_harness.toolkits.memory.graph.exceptions import GraphQueryError

logger = logging.getLogger(__name__)


async def execute_causal_chain(
    conn: aiosqlite.Connection,
    start_id: str,
    depth: int = 5,
    relation_types: list[str] | None = None,
) -> list[str]:
    """Traverse causal chain via recursive CTE with cycle detection, respecting temporal validity."""
    if relation_types is None:
        relation_types = ["causes"]
    try:
        if relation_types:
            base_cond = " AND (" + " OR ".join(["rel_type = ?" for _ in relation_types]) + ")"
            recursive_cond = " AND (" + " OR ".join(["r.rel_type = ?" for _ in relation_types]) + ")"
            params: list[str | int] = [start_id, *relation_types, depth, *relation_types]
        else:
            base_cond = ""
            recursive_cond = ""
            params = [start_id, depth]

        query = f"""
            WITH RECURSIVE causal_chain AS (
                SELECT source_id, target_id, rel_type, 1 as depth,
                       ',' || source_id || ',' || target_id || ',' as path
                FROM graph_relationships
                WHERE source_id = ? AND valid_until IS NULL{base_cond}

                UNION ALL

                SELECT r.source_id, r.target_id, r.rel_type, c.depth + 1,
                       c.path || r.target_id || ','
                    FROM graph_relationships r
                    INNER JOIN causal_chain c ON r.source_id = c.target_id
                    WHERE c.depth < ? AND r.valid_until IS NULL{recursive_cond}
                      AND instr(c.path, ',' || r.target_id || ',') = 0
            )
            SELECT DISTINCT target_id, depth FROM causal_chain ORDER BY depth
        """
        async with conn.execute(query, params) as cursor:
            results = await cursor.fetchall()
        return [str(row[0]) for row in results]
    except Exception as e:
        raise GraphQueryError(f"Causal chain query failed: {e}") from e


async def execute_related_nodes(
    conn: aiosqlite.Connection,
    node_id: str,
    rel_type: str = "MENTIONS",
) -> list[str]:
    """Find co-occurring / related sibling nodes across active relationships."""
    try:
        query = """
            SELECT DISTINCT r2.source_id
            FROM graph_relationships r1
            JOIN graph_relationships r2 ON r1.target_id = r2.target_id
            WHERE r1.source_id = ? AND r1.rel_type = ? AND r1.valid_until IS NULL
              AND r2.rel_type = ? AND r2.source_id != ? AND r2.valid_until IS NULL
        """
        async with conn.execute(query, (node_id, rel_type, rel_type, node_id)) as cursor:
            rows = await cursor.fetchall()
        return [str(row[0]) for row in rows]
    except Exception as e:
        logger.warning("get_related_nodes failed: %s", e)
        return []


async def execute_related_nodes_with_depth(
    conn: aiosqlite.Connection,
    node_id: str,
    rel_type: str = "MENTIONS",
    max_depth: int = 2,
) -> list[tuple[str, int]]:
    """Traverse related sibling nodes with depth via recursive CTE and cycle detection."""
    try:
        query = """
            WITH RECURSIVE related AS (
                SELECT DISTINCT r2.source_id AS node_id, 1 AS depth,
                       ',' || r2.source_id || ',' AS path
                FROM graph_relationships r1
                JOIN graph_relationships r2 ON r1.target_id = r2.target_id
                WHERE r1.source_id = ? AND r1.rel_type = ? AND r1.valid_until IS NULL
                  AND r2.rel_type = ? AND r2.source_id != ? AND r2.valid_until IS NULL

                UNION ALL

                SELECT DISTINCT r2.source_id AS node_id, rd.depth + 1 AS depth,
                       rd.path || r2.source_id || ',' AS path
                FROM related rd
                JOIN graph_relationships r1 ON r1.source_id = rd.node_id
                JOIN graph_relationships r2 ON r1.target_id = r2.target_id
                WHERE r1.rel_type = ? AND r1.valid_until IS NULL
                  AND r2.rel_type = ? AND r2.source_id != ? AND r2.valid_until IS NULL
                  AND instr(rd.path, ',' || r2.source_id || ',') = 0
                  AND rd.depth < ?
            )
            SELECT node_id, MIN(depth) AS depth FROM related
            GROUP BY node_id ORDER BY depth
        """
        params = [node_id, rel_type, rel_type, node_id, rel_type, rel_type, node_id, max_depth]
        async with conn.execute(query, params) as cursor:
            rows = await cursor.fetchall()
        return [(str(row[0]), int(row[1])) for row in rows]
    except Exception as e:
        logger.warning("get_related_nodes_with_depth failed: %s", e)
        return []


async def execute_delete_subgraph(conn: aiosqlite.Connection, node_id: str) -> int:
    """Delete a node and all its connected relationships."""
    try:
        cursor_rels = await conn.execute(
            "DELETE FROM graph_relationships WHERE source_id = ? OR target_id = ?", (node_id, node_id)
        )
        cursor_node = await conn.execute("DELETE FROM graph_nodes WHERE id = ?", (node_id,))
        await conn.commit()
        return cursor_rels.rowcount + cursor_node.rowcount
    except Exception as e:
        logger.warning("delete_subgraph failed for %s: %s", node_id, e)
        return 0


async def execute_delete_all_by_owner(
    conn: aiosqlite.Connection, owner_id: str, *, owner_key: str = "user_id"
) -> int:
    """Delete all nodes and connected relationships whose properties match owner_id."""
    try:
        async with conn.execute(
            f"SELECT id FROM graph_nodes WHERE json_extract(properties, '$.{owner_key}') = ?", (owner_id,)
        ) as cursor:
            node_ids = [row[0] for row in await cursor.fetchall()]

        if not node_ids:
            return 0

        placeholders = ",".join("?" for _ in node_ids)
        cursor_rels = await conn.execute(
            f"DELETE FROM graph_relationships WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})",
            [*node_ids, *node_ids],
        )
        cursor_nodes = await conn.execute(f"DELETE FROM graph_nodes WHERE id IN ({placeholders})", node_ids)
        await conn.commit()
        return cursor_rels.rowcount + cursor_nodes.rowcount
    except Exception as e:
        logger.warning("delete_all_by_owner failed for %s: %s", owner_id, e)
        return 0

