"""Tool result seam chunking packer.

Splits tool outputs into reversible paragraph chunks while preserving whitespace
and document structure, enabling surgical in-place redaction.
Strict typing: No `Any` types allowed.
"""

from __future__ import annotations

import json
import re

from .types import ParagraphChunk

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")


def split_paragraphs(text: str, max_chars: int = 1200) -> list[str]:
    """Split text on blank lines into discrete paragraph slices of at most `max_chars`.

    Each paragraph remains its own independent unit unless it exceeds `max_chars`.
    Invariance guarantee: ''.join(split_paragraphs(text, max_chars)) == text.
    """
    if not text:
        return []

    pieces: list[str] = []
    start = 0
    for match in _PARAGRAPH_SPLIT.finditer(text):
        pieces.append(text[start : match.end()])
        start = match.end()
    pieces.append(text[start:])

    out: list[str] = []
    for piece in pieces:
        if not piece:
            continue
        while len(piece) > max_chars:
            out.append(piece[:max_chars])
            piece = piece[max_chars:]
        if piece:
            out.append(piece)

    return out


def parse_json_safely(result: str) -> dict[str, object] | list[object] | None:
    """Parse JSON without raising exceptions."""
    try:
        parsed: object = json.loads(result)
        if isinstance(parsed, dict):
            typed_dict: dict[str, object] = {str(k): v for k, v in parsed.items()}
            return typed_dict
        if isinstance(parsed, list):
            typed_list: list[object] = list(parsed)
            return typed_list
        return None
    except (TypeError, ValueError):
        return None


def extract_units(
    tool_name: str,
    tool_result: str,
    max_chars: int = 1200,
) -> tuple[dict[str, object] | list[object] | None, list[ParagraphChunk]]:
    """Extract screenable text units and their navigation paths from a tool result."""
    parsed = parse_json_safely(tool_result)
    chunks: list[ParagraphChunk] = []
    chunk_counter = 0

    if isinstance(parsed, dict):
        # 1. Structure: {"data": {"web": [{"title": ..., "description": ...}]}}
        data_val = parsed.get("data")
        if isinstance(data_val, dict):
            web_val = data_val.get("web")
            if isinstance(web_val, list):
                for idx, item in enumerate(web_val):
                    if isinstance(item, dict):
                        for field_name in ("title", "description", "content", "snippet"):
                            f_val = item.get(field_name)
                            if isinstance(f_val, str) and f_val.strip():
                                for sub_idx, piece in enumerate(split_paragraphs(f_val, max_chars)):
                                    chunks.append(
                                        ParagraphChunk(
                                            chunk_id=chunk_counter,
                                            path=("data", "web", idx, field_name, sub_idx),
                                            raw_text=piece,
                                            char_count=len(piece),
                                        )
                                    )
                                    chunk_counter += 1
                if chunks:
                    return parsed, chunks

        # 2. Structure: {"results": [{"title": ..., "content": ...}]}
        results_val = parsed.get("results")
        if isinstance(results_val, list):
            for idx, item in enumerate(results_val):
                if isinstance(item, dict):
                    for field_name in ("title", "snippet", "content", "text", "markdown", "raw_content"):
                        f_val = item.get(field_name)
                        if isinstance(f_val, str) and f_val.strip():
                            for sub_idx, piece in enumerate(split_paragraphs(f_val, max_chars)):
                                chunks.append(
                                    ParagraphChunk(
                                        chunk_id=chunk_counter,
                                        path=("results", idx, field_name, sub_idx),
                                        raw_text=piece,
                                        char_count=len(piece),
                                    )
                                )
                                chunk_counter += 1
            if chunks:
                return parsed, chunks

    # 3. Fallback: Raw text format or generic payload
    raw_pieces = split_paragraphs(tool_result, max_chars)
    for idx, piece in enumerate(raw_pieces):
        chunks.append(
            ParagraphChunk(
                chunk_id=idx,
                path=("raw", idx),
                raw_text=piece,
                char_count=len(piece),
            )
        )
    return parsed, chunks
