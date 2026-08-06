"""Capped body previews for duplicate group review."""

from __future__ import annotations

from myrm_agent_harness.toolkits.wiki.core.structure import WikiStructure
from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.fingerprint import (
    extract_body_text,
)
from myrm_agent_harness.toolkits.wiki.pipeline.corpus_dedup.types import (
    DuplicateGroup,
    DuplicateMemberSnippet,
)


def _cap_snippet(text: str, max_chars: int) -> str:
    collapsed = " ".join(text.split())
    if max_chars <= 0:
        return ""
    if len(collapsed) <= max_chars:
        return collapsed
    if max_chars == 1:
        return "…"
    return collapsed[: max_chars - 1].rstrip() + "…"


def build_group_body_snippets(
    structure: WikiStructure,
    group: DuplicateGroup,
    *,
    max_chars: int = 240,
) -> list[DuplicateMemberSnippet]:
    """Return comparable body excerpts for each member in a duplicate group."""
    snippets: list[DuplicateMemberSnippet] = []
    for member in group.members:
        raw_path = structure.raw_dir / member.relative_path
        content = raw_path.read_text(encoding="utf-8")
        body = extract_body_text(content)
        snippets.append(
            DuplicateMemberSnippet(
                relative_path=member.relative_path,
                snippet=_cap_snippet(body, max_chars),
            )
        )
    return snippets
