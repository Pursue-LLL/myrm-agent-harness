"""Deterministic writers for OKF cognitive map files (index.md, log.md, hot.md).

[INPUT]
..core.structure::WikiStructure (POS: Wiki file system abstraction layer)
..core.frontmatter_contract::validate_wiki_frontmatter, WIKI_PAGE_TYPES (POS: Wiki frontmatter type gate)
.agent.meta_tools.file_ops.utils.markdown_frontmatter::parse_frontmatter (POS: Markdown frontmatter parser)
.snapshot::HotSnapshot, build_hot_snapshot, render_hot_markdown (POS: Hot cache snapshot builder)
.events::WikiMapEvent (POS: Event taxonomy for wiki/log.md entries)

[OUTPUT]
write_index_markdown(), append_log_entry(), write_hot_markdown(): vault file writers
read_hot_context(), read_log_context(): hot.md / log.md readers for wiki_query prefix
count_log_entries(), hot_updated_at_iso(): stats helpers for server /stats API
WikiCognitiveMapService: orchestrates index + log + hot refresh

[POS]
OKF cognitive map writer service. Maintains human-navigable index/log/hot artifacts after wiki lifecycle events.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.agent.meta_tools.file_ops.utils.markdown_frontmatter import parse_frontmatter
from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    WIKI_PAGE_TYPES,
    WikiPageType,
    validate_wiki_frontmatter,
)
from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.utils.logger_utils import get_agent_logger

from .atomic_io import atomic_write_text
from .events import WikiMapEvent
from .schema_writer import write_schema_markdown
from .snapshot import HotSnapshot, build_hot_snapshot, render_hot_markdown

logger = get_agent_logger(__name__)

_LOG_MAX_BYTES = 100_000
_LOG_CONTEXT_MAX_CHARS = 1_500
_SUMMARY_MAX_CHARS = 120


def _atomic_write_text(path: Path, content: str) -> None:
    atomic_write_text(path, content)


def _concept_wikilink_name(concept_path: Path, concepts_dir: Path) -> str:
    rel = concept_path.relative_to(concepts_dir)
    return str(rel.with_suffix("")).replace("\\", "/")


def _one_line_summary(content: str) -> str:
    _metadata, body = parse_frontmatter(content)
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line == "---":
            continue
        if line.startswith("#"):
            return line.lstrip("#").strip()[:_SUMMARY_MAX_CHARS]
        return line[:_SUMMARY_MAX_CHARS]
    return ""


def _index_entry_summary(structure: WikiStructure, concept_path: Path, body_content: str) -> str:
    """Prefer the parent directory L0 .abstract.md one-liner, then concept body."""
    rel = concept_path.relative_to(structure.concepts_dir)
    parent_dir = "" if rel.parent == Path(".") else str(rel.parent).replace("\\", "/")
    abstract_path, _overview_path = structure.get_directory_sidecar_paths(parent_dir, create=False)
    if abstract_path.exists():
        try:
            abstract_summary = _one_line_summary(abstract_path.read_text(encoding="utf-8"))
            if abstract_summary:
                return abstract_summary
        except OSError as exc:
            logger.warning("Skipping abstract summary for %s: %s", abstract_path, exc)
    summary = _one_line_summary(body_content)
    return summary or "Wiki concept page"


def _read_page_type(content: str) -> str:
    validation = validate_wiki_frontmatter(content)
    if validation.ok and validation.page_type:
        return validation.page_type
    return WikiPageType.CONCEPT.value


def write_index_markdown(structure: WikiStructure) -> Path:
    """Write OKF-style wiki/index.md grouped by frontmatter type."""
    index_path = structure.get_index_file_path()
    grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)

    for concept_path in structure.list_concepts():
        try:
            content = concept_path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Skipping index entry for %s: %s", concept_path, exc)
            continue
        page_type = _read_page_type(content)
        link_name = _concept_wikilink_name(concept_path, structure.concepts_dir)
        summary = _index_entry_summary(structure, concept_path, content)
        grouped[page_type].append((link_name, summary))

    lines = [
        "# Wiki Index",
        "",
        f"*Last updated: {datetime.now(UTC).isoformat()}*",
        "",
        "Content catalog grouped by page type. Each entry links to a wiki concept page.",
        "",
    ]
    for page_type in sorted(WIKI_PAGE_TYPES):
        entries = grouped.get(page_type, [])
        if not entries:
            continue
        lines.append(f"## {page_type}")
        lines.append("")
        for link_name, summary in sorted(entries, key=lambda item: item[0].lower()):
            lines.append(f"- [[{link_name}]] — {summary}")
        lines.append("")

    _atomic_write_text(index_path, "\n".join(lines).rstrip() + "\n")
    logger.info("Wrote wiki index: %s", index_path)
    return index_path


def _rotate_log_if_needed(log_path: Path) -> None:
    if not log_path.exists():
        return
    try:
        size = log_path.stat().st_size
    except OSError:
        return
    if size <= _LOG_MAX_BYTES:
        return
    archive_path = log_path.with_name("log.archive.md")
    try:
        archive_path.write_text(log_path.read_text(encoding="utf-8"), encoding="utf-8")
        log_path.write_text("# Wiki activity log\n\n", encoding="utf-8")
    except OSError as exc:
        logger.warning("Failed to rotate wiki log at %s: %s", log_path, exc)


def append_log_entry(structure: WikiStructure, event: WikiMapEvent) -> Path:
    """Append a human-readable entry to wiki/log.md (newest section first)."""
    log_path = structure.get_log_file_path()
    _rotate_log_if_needed(log_path)

    timestamp = datetime.now(UTC).isoformat()
    entry_lines = [
        f"## {timestamp} — {event.event_type.value}",
        "",
        f"- {event.summary}",
    ]
    for key, value in event.details.items():
        entry_lines.append(f"- {key}: {value}")
    entry_lines.append("")
    entry_block = "\n".join(entry_lines)

    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8").strip()
        if existing.startswith("# Wiki activity log"):
            rest = existing.removeprefix("# Wiki activity log").strip()
            content = f"# Wiki activity log\n\n{entry_block}\n\n{rest}\n"
        else:
            content = f"# Wiki activity log\n\n{entry_block}\n\n{existing}\n"
    else:
        content = f"# Wiki activity log\n\n{entry_block}\n"

    _atomic_write_text(log_path, content)
    return log_path


def write_hot_markdown(structure: WikiStructure, snapshot: HotSnapshot) -> Path:
    hot_path = structure.get_hot_file_path()
    _atomic_write_text(hot_path, render_hot_markdown(snapshot))
    logger.info("Wrote wiki hot cache: %s", hot_path)
    return hot_path


def read_hot_context(structure: WikiStructure, *, max_chars: int = 2_000) -> str:
    """Load hot.md for wiki_query context prefix (zero LLM)."""
    hot_path = structure.get_hot_file_path()
    if not hot_path.exists():
        return ""
    try:
        text = hot_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n[truncated]"


def read_log_context(structure: WikiStructure, *, max_chars: int = _LOG_CONTEXT_MAX_CHARS) -> str:
    """Load recent wiki/log.md entries for wiki_query activity context (bounded, zero LLM)."""
    log_path = structure.get_log_file_path()
    if not log_path.exists():
        return ""
    try:
        text = log_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    if not text:
        return ""
    if text.startswith("# Wiki activity log"):
        text = text.removeprefix("# Wiki activity log").strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n[truncated]"


def count_log_entries(structure: WikiStructure) -> int:
    log_path = structure.get_log_file_path()
    if not log_path.exists():
        return 0
    try:
        content = log_path.read_text(encoding="utf-8")
    except OSError:
        return 0
    return len(re.findall(r"^##\s+", content, flags=re.MULTILINE))


def hot_updated_at_iso(structure: WikiStructure) -> str | None:
    hot_path = structure.get_hot_file_path()
    if not hot_path.exists():
        return None
    try:
        mtime = datetime.fromtimestamp(hot_path.stat().st_mtime, tz=UTC)
        return mtime.isoformat()
    except OSError:
        return None


@dataclass(frozen=True, slots=True)
class CognitiveMapRefreshResult:
    index_path: Path
    log_path: Path
    hot_path: Path
    schema_path: Path


class WikiCognitiveMapService:
    """Refresh OKF cognitive map artifacts after wiki lifecycle events."""

    def __init__(
        self,
        structure: WikiStructure,
        *,
        get_pending_count: Callable[[], int] | None = None,
        get_queue_pending: Callable[[], int] | None = None,
    ) -> None:
        self._structure = structure
        self._get_pending_count = get_pending_count
        self._get_queue_pending = get_queue_pending

    def refresh(self, event: WikiMapEvent) -> CognitiveMapRefreshResult:
        index_path = write_index_markdown(self._structure)
        log_path = append_log_entry(self._structure, event)
        pending_count = self._get_pending_count() if self._get_pending_count else 0
        queue_pending = self._get_queue_pending() if self._get_queue_pending else 0
        snapshot = build_hot_snapshot(
            self._structure,
            last_event_summary=event.summary,
            pending_count=pending_count,
            queue_pending=queue_pending,
        )
        hot_path = write_hot_markdown(self._structure, snapshot)
        schema_path = write_schema_markdown(self._structure)
        return CognitiveMapRefreshResult(
            index_path=index_path,
            log_path=log_path,
            hot_path=hot_path,
            schema_path=schema_path,
        )
