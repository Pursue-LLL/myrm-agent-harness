"""Wiki body section contract — Compiled Truth and Timeline managed blocks.

[INPUT]
- frontmatter_contract.load_frontmatter_metadata (POS: split FM from body)

[OUTPUT]
- COMPILED_TRUTH_HEADING, TIMELINE_HEADING, WikiEditorSections, get_section_inner, replace_section_inner
- append_section_entry, build_note_body_skeleton, extract_compiled_truth_summary, parse_editor_sections

[POS]
SSOT for section-aware wiki apply mutations. Protects managed blocks from whole-page overwrites.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from myrm_agent_harness.toolkits.wiki.core.frontmatter_contract import (
    load_frontmatter_metadata,
)

COMPILED_TRUTH_HEADING = "## Compiled Truth"
TIMELINE_HEADING = "## Timeline"

_COMPILED_TRUTH_BODY_RE = re.compile(
    rf"^{re.escape(COMPILED_TRUTH_HEADING)}\n(.*?)(?=\n## |\Z)",
    re.DOTALL | re.MULTILINE,
)
_TIMELINE_BODY_RE = re.compile(
    rf"^{re.escape(TIMELINE_HEADING)}\n(.*?)(?=\n## |\Z)",
    re.DOTALL | re.MULTILINE,
)

_MAX_TIMELINE_ENTRY_CHARS = 8_000
_MAX_TIMELINE_SECTION_CHARS = 120_000


@dataclass(frozen=True, slots=True)
class WikiEditorSections:
    """Parsed managed sections and list metadata for GUI editors."""

    compiled_truth: str
    timeline: str
    tags: tuple[str, ...]
    aliases: tuple[str, ...]


def _coerce_string_list(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            text = str(item).strip()
            if text:
                items.append(text)
        return tuple(items)
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    return ()


def parse_editor_sections(content: str) -> WikiEditorSections:
    """Parse GUI editor fields from concept markdown using harness frontmatter SSOT."""
    metadata, body = load_frontmatter_metadata(content)
    compiled_truth = get_section_inner(body, COMPILED_TRUTH_HEADING) or ""
    timeline = get_section_inner(body, TIMELINE_HEADING) or ""
    return WikiEditorSections(
        compiled_truth=compiled_truth,
        timeline=timeline,
        tags=_coerce_string_list(metadata.get("tags")),
        aliases=_coerce_string_list(metadata.get("aliases")),
    )


def _normalize_entry(text: str) -> str:
    return " ".join(text.strip().split())


def get_section_inner(body: str, heading: str) -> str | None:
    """Return inner markdown for a level-2 section, excluding the heading line."""
    if heading == COMPILED_TRUTH_HEADING:
        match = _COMPILED_TRUTH_BODY_RE.search(body.lstrip("\n"))
    elif heading == TIMELINE_HEADING:
        match = _TIMELINE_BODY_RE.search(body.lstrip("\n"))
    else:
        pattern = re.compile(
            rf"^{re.escape(heading)}\n(.*?)(?=\n## |\Z)",
            re.DOTALL | re.MULTILINE,
        )
        match = pattern.search(body.lstrip("\n"))
    if match is None:
        return None
    return match.group(1).strip("\n")


def replace_section_inner(
    body: str, heading: str, new_inner: str, *, create_if_missing: bool = True
) -> str:
    """Replace a managed section body while preserving other sections."""
    normalized_body = body.lstrip("\n")
    new_block = f"{heading}\n{new_inner.strip()}\n"
    if heading == COMPILED_TRUTH_HEADING:
        match = _COMPILED_TRUTH_BODY_RE.search(normalized_body)
    elif heading == TIMELINE_HEADING:
        match = _TIMELINE_BODY_RE.search(normalized_body)
    else:
        pattern = re.compile(
            rf"^{re.escape(heading)}\n(.*?)(?=\n## |\Z)",
            re.DOTALL | re.MULTILINE,
        )
        match = pattern.search(normalized_body)

    if match is not None:
        start, end = match.span()
        return normalized_body[:start] + new_block + normalized_body[end:].lstrip("\n")

    if not create_if_missing:
        return body

    if heading == TIMELINE_HEADING and COMPILED_TRUTH_HEADING in normalized_body:
        truth_match = _COMPILED_TRUTH_BODY_RE.search(normalized_body)
        if truth_match is not None:
            insert_at = truth_match.end()
            prefix = normalized_body[:insert_at].rstrip("\n") + "\n\n"
            suffix = normalized_body[insert_at:].lstrip("\n")
            rebuilt = prefix + new_block
            if suffix:
                rebuilt += "\n" + suffix
            return rebuilt

    if normalized_body.strip():
        return normalized_body.rstrip("\n") + "\n\n" + new_block
    return new_block


def append_section_entry(body: str, heading: str, entry: str) -> tuple[str, bool]:
    """Append a timeline-style entry. Returns (new_body, appended). Skips duplicates."""
    trimmed = entry.strip()
    if not trimmed:
        raise ValueError("Timeline entry must not be empty")
    if len(trimmed) > _MAX_TIMELINE_ENTRY_CHARS:
        raise ValueError(
            f"Timeline entry exceeds {_MAX_TIMELINE_ENTRY_CHARS} characters"
        )

    existing_inner = get_section_inner(body, heading) or ""
    normalized_entry = _normalize_entry(trimmed)
    for line in existing_inner.splitlines():
        cleaned = line.strip().lstrip("-*").strip()
        if cleaned and _normalize_entry(cleaned) == normalized_entry:
            return body, False

    combined = existing_inner.rstrip("\n")
    if combined:
        combined += "\n"
    combined += f"- {trimmed}"
    if len(combined) > _MAX_TIMELINE_SECTION_CHARS:
        raise ValueError(
            f"Timeline section exceeds {_MAX_TIMELINE_SECTION_CHARS} characters"
        )

    return replace_section_inner(body, heading, combined), True


def build_note_body_skeleton(
    *, compiled_truth: str, timeline_entry: str | None = None
) -> str:
    """Build a new concept body with managed sections."""
    truth = compiled_truth.strip() or "_No summary yet._"
    timeline = timeline_entry.strip() if timeline_entry else ""
    timeline_block = timeline or "_No timeline entries yet._"
    if timeline and not timeline.startswith("- "):
        timeline_block = f"- {timeline}"
    return (
        f"{COMPILED_TRUTH_HEADING}\n{truth}\n\n{TIMELINE_HEADING}\n{timeline_block}\n"
    )


def extract_compiled_truth_summary(content: str) -> str:
    """Extract the first meaningful line from Compiled Truth for claim reconciliation."""
    _, body = load_frontmatter_metadata(content)
    inner = get_section_inner(body, COMPILED_TRUTH_HEADING)
    if not inner:
        return ""
    for line in inner.splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned and not cleaned.startswith(">"):
            return cleaned[:240]
    return ""
