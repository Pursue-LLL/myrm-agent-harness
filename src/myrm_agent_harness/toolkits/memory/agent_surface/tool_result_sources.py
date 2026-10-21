"""Helpers for memory_search_tool results that carry SourceTracker sources.

[OUTPUT]
- unpack_corpus_tool_result: Split str or {content, metadata.sources} tool payloads.
- pack_tool_result_with_sources: Always build `{content, metadata:{sources}}` for SourceTracker.

[POS]
Shared contract helpers for memory_search corpus formatters (wiki/sessions/all).
"""

from __future__ import annotations


def unpack_corpus_tool_result(result: str | dict[str, object]) -> tuple[str, list[dict[str, object]]]:
    """Return tool text and any embedded sources list from a corpus formatter result."""
    if isinstance(result, str):
        return result, []
    content_obj = result.get("content")
    content = content_obj if isinstance(content_obj, str) else str(content_obj or "")
    metadata = result.get("metadata")
    if not isinstance(metadata, dict):
        return content, []
    raw_sources = metadata.get("sources")
    if not isinstance(raw_sources, list):
        return content, []
    sources: list[dict[str, object]] = []
    for item in raw_sources:
        if isinstance(item, dict):
            sources.append(dict(item))
    return content, sources


def pack_tool_result_with_sources(
    content: str,
    sources: list[dict[str, object]],
) -> dict[str, object]:
    """Attach sources for SourceTracker; always returns a dict payload."""
    return {"content": content, "metadata": {"sources": sources}}
