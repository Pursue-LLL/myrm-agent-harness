"""Wiki knowledge graph storage and BFS traversal.

[INPUT]
- sqlite3 (POS: standard library database)
- ..core.structure::WikiStructure (POS: database path resolution)
- .graph_analysis::enrich_graph_with_communities, compute_graph_insights (POS: graph analysis)

[OUTPUT]
- WikiGraphStore: Graph topology storage, BFS traversal, and insight computation

[POS]
Encapsulates knowledge graph operations: BFS neighbor traversal, federated
graph queries across public wiki databases, and structural insight computation.
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import TYPE_CHECKING

from .graph_analysis import compute_graph_insights, enrich_graph_with_communities

if TYPE_CHECKING:
    from ..core.structure import WikiStructure

ConnFactory = Callable[[], AbstractContextManager[sqlite3.Connection]]

logger = logging.getLogger(__name__)


class WikiGraphStore:
    """Knowledge graph storage and BFS traversal over federated wiki databases."""

    def __init__(self, get_conn_fn: ConnFactory, structure: WikiStructure) -> None:
        self._get_conn = get_conn_fn
        self._structure = structure

    def get_knowledge_graph(
        self, center_node: str | None = None, depth: int = 1, limit: int = 1000
    ) -> dict[str, list[dict[str, object]]]:
        """Fetch the full topology graph in O(1) DB read time, with progressive BFS support."""
        nodes: list[dict[str, object]] = []
        edges: list[dict[str, object]] = []
        node_ids: set[str] = set()

        with self._get_conn() as conn:
            fts_tables = ["wiki_fts"]
            edges_tables = ["wiki_edges"]
            attached_dbs = {str(row["name"]) for row in conn.execute("PRAGMA database_list").fetchall()}
            for idx in range(min(len(self._structure.public_dirs), 6)):
                alias = f"pub_{idx}"
                if alias in attached_dbs:
                    try:
                        has_fts = conn.execute(
                            f"SELECT 1 FROM {alias}.sqlite_master WHERE type IN ('table', 'view') AND name = 'wiki_fts'"
                        ).fetchone()
                        has_edges = conn.execute(
                            f"SELECT 1 FROM {alias}.sqlite_master WHERE type IN ('table', 'view') AND name = 'wiki_edges'"
                        ).fetchone()
                        if has_fts:
                            fts_tables.append(f"{alias}.wiki_fts")
                        if has_edges:
                            edges_tables.append(f"{alias}.wiki_edges")
                    except (sqlite3.OperationalError, sqlite3.DatabaseError):
                        continue

            fts_union = " UNION ALL ".join(f"SELECT concept_name FROM {t}" for t in fts_tables)
            edges_union = " UNION ALL ".join(f"SELECT source, target, weight FROM {t}" for t in edges_tables)

            if not center_node:
                cursor = conn.execute(f"SELECT concept_name FROM ({fts_union}) LIMIT ?", (limit,))
                for row in cursor.fetchall():
                    node_id = row["concept_name"]
                    nodes.append({"id": node_id, "name": node_id.replace("-", " "), "group": 1})
                    node_ids.add(node_id)

                if node_ids:
                    cursor = conn.execute(f"SELECT source, target, weight FROM ({edges_union})")
                    for row in cursor.fetchall():
                        src = row["source"]
                        tgt = row["target"]
                        if src in node_ids and tgt in node_ids:
                            edges.append(
                                {
                                    "source": src,
                                    "target": tgt,
                                    "weight": row["weight"] or 1.0,
                                }
                            )
            else:
                nodes, edges = self._bfs_from_center(conn, center_node, depth, limit, fts_union, edges_union)

        enrich_graph_with_communities(nodes, edges)
        return {"nodes": nodes, "edges": edges}

    def _bfs_from_center(
        self,
        conn: sqlite3.Connection,
        center_node: str,
        depth: int,
        limit: int,
        fts_union: str,
        edges_union: str,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        """BFS starting from center_node across federated databases."""
        nodes: list[dict[str, object]] = []
        current_level = {center_node}
        visited_nodes = {center_node}
        all_edges: list[dict[str, object]] = []

        cursor = conn.execute(
            f"SELECT concept_name FROM ({fts_union}) WHERE concept_name = ?",
            (center_node,),
        )
        if cursor.fetchone() or self._find_asset_path(center_node) is not None:
            nodes.append(
                {
                    "id": center_node,
                    "name": center_node.replace("-", " "),
                    "group": 1,
                }
            )

        for _ in range(depth):
            if not current_level:
                break
            next_level: set[str] = set()

            placeholders = ",".join(["?"] * len(current_level))
            params = tuple(current_level)

            cursor = conn.execute(
                f"SELECT source, target, weight FROM ({edges_union}) WHERE source IN ({placeholders})",
                params,
            )
            for row in cursor.fetchall():
                src, tgt = row["source"], row["target"]
                all_edges.append(
                    {
                        "source": src,
                        "target": tgt,
                        "weight": row["weight"] or 1.0,
                    }
                )
                if tgt not in visited_nodes:
                    next_level.add(tgt)

            cursor = conn.execute(
                f"SELECT source, target, weight FROM ({edges_union}) WHERE target IN ({placeholders})",
                params,
            )
            for row in cursor.fetchall():
                src, tgt = row["source"], row["target"]
                all_edges.append(
                    {
                        "source": src,
                        "target": tgt,
                        "weight": row["weight"] or 1.0,
                    }
                )
                if src not in visited_nodes:
                    next_level.add(src)

            if next_level:
                np_placeholders = ",".join(["?"] * len(next_level))
                np_params = tuple(next_level)
                cursor = conn.execute(
                    f"SELECT concept_name FROM ({fts_union}) WHERE concept_name IN ({np_placeholders})",
                    np_params,
                )
                found_in_fts = {row["concept_name"] for row in cursor.fetchall()}
                for nid in next_level:
                    if nid not in visited_nodes and (nid in found_in_fts or self._find_asset_path(nid) is not None):
                        nodes.append(
                            {
                                "id": nid,
                                "name": nid.replace("-", " "),
                                "group": 1,
                            }
                        )
                        visited_nodes.add(nid)

            current_level = next_level
            if len(visited_nodes) >= limit:
                break

        unique_edges: dict[tuple[str, str], dict[str, object]] = {}
        for e in all_edges:
            if e["source"] in visited_nodes and e["target"] in visited_nodes:
                unique_edges[(e["source"], e["target"])] = e

        return nodes, list(unique_edges.values())

    def graph_insights(self) -> dict[str, list[dict[str, object]]]:
        """Analyze graph structure for unexpected connections, knowledge gaps, and communities."""
        with self._get_conn() as conn:
            return compute_graph_insights(conn)

    def _find_asset_path(self, name: str) -> Path | None:
        """Locate markdown asset path across concepts, deliverables, methods, and claims."""
        clean_name = name.removesuffix(".md").strip()
        # 1. Concept path
        path = self._structure.resolve_concept_file_path(clean_name)
        if path and path.is_file():
            return path
        # 2. Deliverables
        deliv = self._structure.get_deliverable_file_path(f"{clean_name}.md")
        if deliv.is_file():
            return deliv
        # 3. Methods
        method = self._structure.get_method_file_path(clean_name)
        if method.is_file():
            return method
        # 4. Claims
        claim = self._structure.get_claim_file_path(clean_name)
        if claim.is_file():
            return claim
        # 5. Frontmatter alias lookup
        alias_path = self._structure.resolve_alias_file_path(clean_name)
        if alias_path and alias_path.is_file():
            return alias_path
        return None

    def _get_target_aliases(self, clean_name: str) -> list[str]:
        """Resolve concept frontmatter aliases to ensure backlinks match mentions under aliases."""
        path = self._structure.resolve_concept_file_path(clean_name)
        if not path or not path.is_file():
            return []
        try:
            from myrm_agent_harness.utils.markdown_frontmatter import parse_frontmatter

            with open(path, encoding="utf-8", errors="ignore") as f:
                chunk = f.read(2048)
            fm, _ = parse_frontmatter(chunk)
            aliases = fm.get("aliases")
            if isinstance(aliases, list):
                return [str(a).strip() for a in aliases if str(a).strip()]
            if isinstance(aliases, str) and aliases.strip():
                return [a.strip() for a in aliases.split(",") if a.strip()]
        except Exception:
            pass
        return []

    def _extract_mention_record(
        self, file_path: Path, target_name: str, max_chars: int = 140
    ) -> tuple[str, int, str | None] | None:
        """Extract snippet, 1-based line number, and heading section where target_name is referenced."""
        if not file_path.is_file():
            return None
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None

        clean_target = target_name.removesuffix(".md").strip()
        if not clean_target:
            return None

        target_names = [clean_target]
        for a in self._get_target_aliases(clean_target):
            if a and a not in target_names:
                target_names.append(a)

        patterns: list[re.Pattern[str]] = []
        for name in target_names:
            escaped_target = re.escape(name)
            has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in name)
            patterns.append(re.compile(rf"\[\[{escaped_target}(?:[#|][^\]]*)?\]\]", re.IGNORECASE))
            patterns.append(re.compile(rf"\[[^\]]+\]\([^)]*{escaped_target}[^)]*\)", re.IGNORECASE))
            if has_cjk:
                if len(name) >= 2:
                    patterns.append(re.compile(rf"(?<![a-zA-Z0-9]){escaped_target}(?![a-zA-Z0-9])", re.IGNORECASE))
            else:
                patterns.append(re.compile(rf"\b{escaped_target}\b", re.IGNORECASE))

        current_heading: str | None = None
        for line_idx, line in enumerate(content.splitlines(), start=1):
            line_str = line.strip()
            if not line_str:
                continue
            if line_str.startswith("#"):
                current_heading = line_str.lstrip("#").strip()
                continue

            for pattern in patterns:
                if pattern.search(line_str):
                    clean_line = re.sub(r"^[-*+>]\s+", "", line_str).strip()
                    snippet = clean_line
                    if len(clean_line) > max_chars:
                        match = pattern.search(clean_line)
                        if match:
                            start = max(0, match.start() - 30)
                            end = min(len(clean_line), match.end() + 70)
                            prefix = "..." if start > 0 else ""
                            suffix = "..." if end < len(clean_line) else ""
                            snippet = f"{prefix}{clean_line[start:end].strip()}{suffix}"
                        else:
                            snippet = f"{clean_line[:max_chars]}..."
                    return snippet, line_idx, current_heading
        return None

    def _extract_mention_snippet(self, file_path: Path, target_name: str, max_chars: int = 140) -> str | None:
        """Extract a readable snippet showing the sentence or context where target_name is referenced."""
        rec = self._extract_mention_record(file_path, target_name, max_chars)
        return rec[0] if rec else None

    def get_concept_links(self, concept_name: str, depth: int = 1) -> dict[str, object]:
        """Fetch bidirectional links (outlinks and backlinks) with context snippets and 1-degree ego graph."""
        clean_name = concept_name.removesuffix(".md").strip()

        outlinks: list[dict[str, object]] = []
        backlinks: list[dict[str, object]] = []

        with self._get_conn() as conn:
            # Query outgoing edges (what this concept references)
            cursor = conn.execute(
                "SELECT target, weight FROM wiki_edges WHERE source = ? ORDER BY weight DESC LIMIT 100",
                (clean_name,),
            )
            for row in cursor.fetchall():
                tgt = str(row["target"])
                tgt_path = self._find_asset_path(tgt)
                outlinks.append(
                    {
                        "name": tgt,
                        "weight": float(row["weight"] or 1.0),
                        "exists": tgt_path is not None,
                        "context_snippet": None,
                    }
                )

            # Query incoming edges (what references this concept)
            cursor = conn.execute(
                "SELECT source, weight FROM wiki_edges WHERE target = ? ORDER BY weight DESC LIMIT 100",
                (clean_name,),
            )
            for row in cursor.fetchall():
                src = str(row["source"])
                src_path = self._find_asset_path(src)
                record = self._extract_mention_record(src_path, clean_name) if src_path else None
                snippet = record[0] if record else None
                line_no = record[1] if record else None
                heading = record[2] if record else None
                backlinks.append(
                    {
                        "name": src,
                        "weight": float(row["weight"] or 1.0),
                        "exists": src_path is not None,
                        "context_snippet": snippet,
                        "line_number": line_no,
                        "heading": heading,
                    }
                )

        # 1-degree ego graph for micro topology rendering
        ego_graph = self.get_knowledge_graph(center_node=clean_name, depth=depth, limit=40)

        return {
            "concept_name": clean_name,
            "outlinks": outlinks,
            "backlinks": backlinks,
            "ego_graph": ego_graph,
        }
