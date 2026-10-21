"""Build zero-LLM hot.md snapshot content from vault state.

[INPUT]
- ..core.structure::WikiStructure (POS: Wiki file system abstraction layer)

[OUTPUT]
- HotSnapshot: immutable hot.md section data
- build_hot_snapshot: derive snapshot from vault filesystem state
- render_hot_markdown: render Molio-style hot.md body

[POS]
Hot cache snapshot builder. Derives recent ops, key pages, and open questions without LLM calls.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure


@dataclass(frozen=True, slots=True)
class HotSnapshot:
    recent_ops: tuple[str, ...]
    key_pages: tuple[tuple[str, str], ...]
    open_questions: tuple[str, ...]


def _read_metadata_concept_count(metadata_path: Path) -> int | None:
    if not metadata_path.exists():
        return None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        total = payload.get("total_concepts")
        return int(total) if isinstance(total, int) else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def build_hot_snapshot(
    structure: WikiStructure,
    *,
    last_event_summary: str,
    pending_count: int = 0,
    queue_pending: int = 0,
) -> HotSnapshot:
    """Derive hot cache sections from vault filesystem state (no LLM)."""
    concept_paths = structure.list_concepts()
    concept_count = len(concept_paths)
    metadata_count = _read_metadata_concept_count(structure.get_wiki_metadata_path())
    if metadata_count is not None:
        concept_count = metadata_count

    recent_ops: list[str] = [last_event_summary]
    if queue_pending > 0:
        recent_ops.append(f"Ingestion queue: {queue_pending} file(s) pending compilation")
    if pending_count > 0:
        recent_ops.append(f"HITL pending edits: {pending_count} awaiting review")

    key_pages: list[tuple[str, str]] = []
    for path in concept_paths[:5]:
        rel = path.relative_to(structure.concepts_dir)
        wiki_name = str(rel.with_suffix("")).replace("\\", "/")
        key_pages.append((wiki_name, "Indexed concept page"))

    open_questions: list[str] = []
    if pending_count > 0:
        open_questions.append("Review pending wiki edits in Settings → Wiki")
    if queue_pending > 0:
        open_questions.append("Wait for compile queue to finish or run Compile")
    if concept_count == 0:
        open_questions.append("Import or ingest sources to seed the wiki vault")

    if not open_questions:
        open_questions.append("Run Maintain periodically to keep links and types healthy")

    return HotSnapshot(
        recent_ops=tuple(recent_ops[:6]),
        key_pages=tuple(key_pages),
        open_questions=tuple(open_questions[:4]),
    )


def render_hot_markdown(snapshot: HotSnapshot) -> str:
    """Render Molio-style three-section hot.md body."""
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Recent context",
        "",
        f"> Last updated: {timestamp}",
        "",
        "## Recent operations",
    ]
    for item in snapshot.recent_ops:
        lines.append(f"- {item}")
    lines.extend(["", "## Key pages"])
    for name, reason in snapshot.key_pages:
        lines.append(f"- [[{name}]] — {reason}")
    lines.extend(["", "## Open questions"])
    for question in snapshot.open_questions:
        lines.append(f"- {question}")
    lines.append("")
    return "\n".join(lines)
