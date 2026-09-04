"""Index-first routing helpers for wiki_query (Karpathy OKF index.md catalog).

[INPUT]
- ..core.structure::WikiStructure (POS: Wiki file system abstraction layer)
- ..retrieval.tokenizer::extract_query_terms (POS: FTS5 tokenizer with CJK bigram support)

[OUTPUT]
- IndexRouteEntry: Parsed index.md catalog row
- parse_index_entries, read_index_entries: Load OKF index catalog
- match_index_entries: Score query against catalog rows
- format_index_route_context: L0 index routing block for wiki_query answers
- INDEX_ROUTING_SECTION: Machine section id for citation metadata (FE i18n key)

[POS]
OKF index-first routing helpers. Seeds wiki_query retrieval from wiki/index.md before
sidecar and FTS fallbacks, with CJK-aware token overlap aligned to the FTS tokenizer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.retrieval.tokenizer import extract_query_terms

_INDEX_ENTRY_RE = re.compile(r"^-\s+\[\[([^\]]+)\]\]\s*(?:—|-)\s*(.+)$")
INDEX_ROUTING_SECTION = "index_routing"


@dataclass(frozen=True, slots=True)
class IndexRouteEntry:
    """One catalog row from wiki/index.md."""

    link_name: str
    summary: str
    page_type: str = ""


def parse_index_entries(content: str) -> list[IndexRouteEntry]:
    """Parse OKF index.md bullet rows grouped by `## page_type` sections."""
    entries: list[IndexRouteEntry] = []
    current_type = ""
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            current_type = line[3:].strip()
            continue
        match = _INDEX_ENTRY_RE.match(line)
        if not match:
            continue
        entries.append(
            IndexRouteEntry(
                link_name=match.group(1).strip(),
                summary=match.group(2).strip(),
                page_type=current_type,
            )
        )
    return entries


def read_index_entries(structure: WikiStructure) -> list[IndexRouteEntry]:
    """Load and parse wiki/index.md when present."""
    index_path = structure.get_index_file_path()
    if not index_path.exists():
        return []
    try:
        content = index_path.read_text(encoding="utf-8")
    except OSError:
        return []
    return parse_index_entries(content)


def score_index_entry(query: str, entry: IndexRouteEntry) -> float:
    """Score query ↔ index row overlap (link name weighted higher than summary)."""
    query_tokens = extract_query_terms(query)
    if not query_tokens:
        return 0.0

    name_tokens = extract_query_terms(entry.link_name.replace("/", " "))
    summary_tokens = extract_query_terms(entry.summary)
    name_overlap = len(query_tokens & name_tokens)
    summary_overlap = len(query_tokens & summary_tokens)
    raw_score = name_overlap * 2.0 + summary_overlap * 1.0
    if raw_score <= 0:
        return 0.0
    return raw_score / max(len(query_tokens), 1)


def match_index_entries(
    query: str,
    entries: list[IndexRouteEntry],
    *,
    max_hits: int,
    min_score: float = 0.25,
) -> list[tuple[IndexRouteEntry, float]]:
    """Return top index rows whose score meets ``min_score``."""
    if max_hits <= 0 or not entries:
        return []

    scored: list[tuple[IndexRouteEntry, float]] = []
    for entry in entries:
        score = score_index_entry(query, entry)
        if score >= min_score:
            scored.append((entry, score))

    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:max_hits]


def format_index_route_context(matches: list[tuple[IndexRouteEntry, float]]) -> str:
    """Human-readable L0 index routing block for wiki_query answers."""
    if not matches:
        return ""

    lines = ["## Index routing (L0)", ""]
    for entry, score in matches:
        type_suffix = f" [{entry.page_type}]" if entry.page_type else ""
        lines.append(f"- [[{entry.link_name}]]{type_suffix} — {entry.summary} (match={score:.2f})")
    return "\n".join(lines)
