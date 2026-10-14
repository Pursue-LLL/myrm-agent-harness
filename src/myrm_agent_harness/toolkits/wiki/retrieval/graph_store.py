"""Wiki knowledge graph storage and BFS traversal.

[INPUT]
- sqlite3 (POS: standard library database)
- ..core.structure::WikiStructure (POS: database path resolution)
- ..core.link_extraction::WIKILINK_RE (POS: the `[[wikilink]]` syntax)
- ..core.link_resolver::concept_index_key, link_lookup_forms, page_link_forms, page_lookup_keys (POS: page-key canonicalization and the spellings a link names a page by)
- myrm_agent_harness.utils.markdown_frontmatter::parse_frontmatter (POS: page aliases)
- .graph_analysis::enrich_graph_with_communities, compute_graph_insights (POS: graph analysis)
- .graph_tables::federated_graph_queries (POS: graph node/edge rows shared with the insights)

[OUTPUT]
- WikiGraphStore: Graph topology storage, BFS traversal, concept link lookup (any spelling of a page name) with the line, section and text of the link each backlink holds, and insight computation

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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.utils.markdown_frontmatter import parse_frontmatter

from ..core.link_extraction import WIKILINK_RE
from ..core.link_resolver import concept_index_key, link_lookup_forms, page_link_forms, page_lookup_keys
from .graph_analysis import compute_graph_insights, enrich_graph_with_communities
from .graph_tables import federated_graph_queries

if TYPE_CHECKING:
    from ..core.structure import WikiStructure

ConnFactory = Callable[[], AbstractContextManager[sqlite3.Connection]]

logger = logging.getLogger(__name__)


def _clean_heading_text(raw_heading: str) -> str:
    """Strip markdown formatting (links, bold, code, tags) to produce a pure heading title."""
    text = raw_heading.strip()
    text = re.sub(r"^#{1,6}\s*", "", text)
    # Strip wikilinks: [[target|display]] -> display, [[target]] -> target
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", text)
    # Strip markdown links and images: [text](url) -> text, ![alt](url) -> alt
    text = re.sub(r"!?\[([^\]]*)\]\([^)]+\)", r"\1", text)
    # Strip inline code: `code` -> code
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Strip bold and italics: **text**, __text__, *text*, _text_
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    # Strip strikethrough: ~~text~~ -> text
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True, slots=True)
class _TargetSpellings:
    """How other pages refer to a target page; built once per lookup, matched against every backlink.

    ``link_forms`` are the casefolded spellings a ``[[wikilink]]`` resolves to the page by (path,
    title, alias, canonical id, bare file name), exactly as the link resolver reads them.
    ``patterns`` find markdown links and plain-text mentions of the page key and its aliases.
    """

    link_forms: frozenset[str]
    patterns: tuple[re.Pattern[str], ...]


def _frontmatter_aliases(markdown: str) -> list[str]:
    raw = parse_frontmatter(markdown)[0].get("aliases")
    if isinstance(raw, list):
        return [alias for item in raw if (alias := str(item).strip())]
    if isinstance(raw, str):
        return [alias for item in raw.split(",") if (alias := item.strip())]
    return []


def _mention_patterns(names: tuple[str, ...]) -> tuple[re.Pattern[str], ...]:
    patterns: list[re.Pattern[str]] = []
    for name in names:
        escaped = re.escape(name)
        patterns.append(re.compile(rf"\[[^\]]+\]\([^)]*{escaped}[^)]*\)", re.IGNORECASE))
        if any("\u4e00" <= ch <= "\u9fff" for ch in name):
            if len(name) >= 2:
                patterns.append(re.compile(rf"(?<![a-zA-Z0-9]){escaped}(?![a-zA-Z0-9])", re.IGNORECASE))
        else:
            patterns.append(re.compile(rf"\b{escaped}\b", re.IGNORECASE))
    return tuple(patterns)


def _first_mention(line: str, target: _TargetSpellings) -> tuple[int, int] | None:
    """Span of the first wikilink naming the target, else of the first markdown link or plain mention."""
    for link in WIKILINK_RE.finditer(line):
        if any(form and form in target.link_forms for form in link_lookup_forms(link.group(1))):
            return link.span()
    for pattern in target.patterns:
        if mention := pattern.search(line):
            return mention.span()
    return None


def _snippet_around(line: str, span: tuple[int, int], max_chars: int) -> str:
    """The line itself, or a window of it around ``span`` when it is longer than ``max_chars``."""
    if len(line) <= max_chars:
        return line
    start = max(0, span[0] - 30)
    end = min(len(line), span[1] + 70)
    return f"{'...' if start > 0 else ''}{line[start:end].strip()}{'...' if end < len(line) else ''}"


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
            fts_union, edges_union = federated_graph_queries(conn)

            if not center_node:
                cursor = conn.execute(f"SELECT concept_name FROM ({fts_union}) LIMIT ?", (limit,))
                for row in cursor.fetchall():
                    node_id = row["concept_name"]
                    nodes.append({"id": node_id, "name": node_id.replace("-", " "), "group": 1})
                    node_ids.add(node_id)

                if node_ids:
                    cursor = conn.execute(f"SELECT source, target, weight FROM ({edges_union})")
                    edge_weights: dict[tuple[str, str], float] = {}
                    for row in cursor.fetchall():
                        src = row["source"]
                        tgt = row["target"]
                        if src in node_ids and tgt in node_ids:
                            weight = float(row["weight"] or 1.0)
                            edge_weights[(src, tgt)] = max(edge_weights.get((src, tgt), 0.0), weight)
                    edges = [
                        {"source": src, "target": tgt, "weight": weight} for (src, tgt), weight in edge_weights.items()
                    ]
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

    def _target_spellings(self, name: str) -> _TargetSpellings:
        """Spellings other pages use for ``name``, read from the whole page the way the link resolver reads it."""
        key = name.removesuffix(".md").strip()
        if not key:
            return _TargetSpellings(frozenset(), ())
        path = self._structure.resolve_concept_file_path(key)
        markdown = ""
        if path is not None and path.is_file():
            try:
                markdown = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                markdown = ""
        names = tuple(dict.fromkeys((key, *_frontmatter_aliases(markdown))))
        return _TargetSpellings(page_link_forms(key, page_lookup_keys(key, markdown)), _mention_patterns(names))

    def _extract_mention_record(
        self, file_path: Path, target: _TargetSpellings, max_chars: int = 140
    ) -> tuple[str, int, str | None] | None:
        """Snippet, 1-based line number and heading section of the first line of ``file_path`` that mentions ``target``."""
        if not file_path.is_file():
            return None
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None

        current_heading: str | None = None
        for line_no, line in enumerate(content.splitlines(), start=1):
            text = line.strip()
            if not text:
                continue
            if text.startswith("#"):
                current_heading = _clean_heading_text(text)
                continue
            clean_line = re.sub(r"^[-*+>]\s+", "", text).strip()
            span = _first_mention(clean_line, target)
            if span is not None:
                return _snippet_around(clean_line, span, max_chars), line_no, current_heading
        return None

    def get_concept_links(self, concept_name: str, depth: int = 1) -> dict[str, object]:
        """Fetch bidirectional links (outlinks and backlinks) with context snippets and 1-degree ego graph."""
        clean_name = concept_index_key(self._structure, concept_name.removesuffix(".md").strip())
        spellings = self._target_spellings(clean_name)

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
                record = self._extract_mention_record(src_path, spellings) if src_path else None
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
