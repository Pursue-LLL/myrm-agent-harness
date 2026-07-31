"""Deterministic SCHEMA.md writer for Karpathy Layer 3 vault contract.

[INPUT]
..core.frontmatter_contract::WIKI_PAGE_TYPES, WikiPageType (POS: type enum SSOT)
..core.structure::WikiStructure (POS: vault paths)

[OUTPUT]
render_schema_markdown(): human-readable schema body from code contract
write_schema_markdown(): atomic write to wiki/SCHEMA.md

[POS]
OKF schema contract file generator. Keeps vault-facing SCHEMA.md aligned with compile/lint gates.
"""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import WIKI_PAGE_TYPES, WikiPageType
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure

from .atomic_io import atomic_write_text

_INDEX_CONTEXT_MAX_CHARS = 2_000


def render_schema_markdown() -> str:
    """Build SCHEMA.md content from the harness frontmatter contract SSOT."""
    type_lines = "\n".join(f"- `{page_type}`" for page_type in sorted(WIKI_PAGE_TYPES))
    return f"""# Wiki Schema

Machine-regenerated contract aligned with compile and lint gates. Human edits in Obsidian are
overwritten on the next compile or maintain refresh — customize types via compile policy SSOT.

## Page types

Every wiki page under `wiki/concepts/` must declare a `type` in frontmatter. Allowed values:

{type_lines}

## Conventions

- File names: lowercase, hyphens, nested paths allowed (e.g. `research/transformer-architecture`)
- Link concepts with `[[wikilinks]]`; prefer at least two outbound links on synthesis pages
- Raw sources under `raw/` are immutable; compile updates concept pages instead
- Human activity is recorded in `wiki/log.md`; the catalog lives in `wiki/index.md`
- Session context cache: `wiki/hot.md` (auto-generated)

## Update policy

- When new facts contradict compiled truth, update `## Compiled Truth` and append evidence to `## Timeline`
- Do not delete YAML frontmatter keys enforced by the compile gate
- Comparison / evolution pages use `{WikiPageType.COMPARISON.value}` and live under `Comparisons/` when staged

## Related files

- `wiki/purpose.md` — knowledge base direction (optional, user-editable)
- `wiki/index.md` — sectioned catalog with one-line summaries
- `wiki/log.md` — chronological maintenance and ingest audit log
"""


def write_schema_markdown(structure: WikiStructure) -> Path:
    """Write or refresh wiki/SCHEMA.md from the harness contract SSOT."""
    schema_path = structure.get_schema_file_path()
    atomic_write_text(schema_path, render_schema_markdown())
    return schema_path


def read_index_context(structure: WikiStructure, *, max_chars: int = _INDEX_CONTEXT_MAX_CHARS) -> str:
    """Load wiki/index.md for compile concept extraction (bounded, zero LLM)."""
    index_path = structure.get_index_file_path()
    if not index_path.exists():
        return ""
    try:
        text = index_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n[truncated]"
