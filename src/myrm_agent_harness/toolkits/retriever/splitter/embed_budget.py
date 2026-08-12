"""Force-split text chunks to fit embedding model input windows.

[INPUT]
retriever.embedding.window_policy::EmbedWindowPolicy (POS: embed window SSOT)
retriever.splitter.splitter::TextChunker (POS: markdown-aware chunking)
utils.text_utils::get_token_count (POS: tiktoken counting)

[OUTPUT]
split_for_embedding(): split text so every chunk fits the embed budget

[POS]
Embed-time chunking helper. Used by wiki indexers and memory storage before embed_batch.
Wordpiece models (bge/bce/nomic) chunk on character count because one CJK char maps to
one wordpiece token while o200k undercounts CJK; BPE models keep tiktoken-based
chunking on o200k tokens.
"""

from __future__ import annotations

import re

from myrm_agent_harness.toolkits.retriever.embedding.window_policy import (
    EmbedWindowPolicy,
    is_cjk_wordpiece_model,
)
from myrm_agent_harness.toolkits.retriever.splitter.code_utils import _split_by_lines
from myrm_agent_harness.toolkits.retriever.splitter.splitter import TextChunker
from myrm_agent_harness.utils.text_utils import get_token_count

# Matches SmartMarkdownHeaderTextSplitter's heading detection (^#\s+...), folded to
# a single regex so the wordpiece character path aligns section headings with their
# content instead of burying a heading mid-chunk. Code fences (```) shadow headings
# the same way SmartMarkdownHeaderTextSplitter's code_pattern excludes them.
_HEADER_LINE_RE = re.compile(r"^#{1,6}\s+")
_CODE_FENCE_RE = re.compile(r"^```")


def split_for_embedding(text: str, policy: EmbedWindowPolicy) -> list[str]:
    """Split *text* into chunks that each fit ``policy.effective_chunk_budget``.

    Wordpiece models (bge/bce/nomic) tokenize one CJK char as one token while
    o200k undercounts CJK (~2 chars/token), so for them the effective budget is a
    character count and chunking is character-based to keep every chunk inside the
    provider window. BPE models keep the o200k token budget.
    """
    stripped = text.strip()
    if not stripped:
        return []

    if is_cjk_wordpiece_model(policy.model):
        chunks = _split_by_character_budget(stripped, policy.effective_chunk_budget)
    else:
        chunks = _split_by_token_budget(stripped, policy.effective_chunk_budget)
    return [part.strip() for part in chunks if part.strip()]


def _split_by_token_budget(text: str, max_tokens: int) -> list[str]:
    """tiktoken-based embed-time chunking for BPE models."""
    if get_token_count(text) <= max_tokens:
        return [text]

    chunker = TextChunker(min_chunk_tokens=min(200, max_tokens // 4))
    docs = chunker.chunk_text(
        text,
        document_metadata={"title": "embed"},
        max_chunk_tokens=max_tokens,
    )
    chunks = [doc.page_content.strip() for doc in docs if doc.page_content.strip()]
    if not chunks:
        chunks = [text]

    bounded: list[str] = []
    for chunk in chunks:
        bounded.extend(_enforce_chunk_budget(chunk, max_tokens))
    return bounded


def _split_by_character_budget(text: str, max_chars: int) -> list[str]:
    """Character-count chunking for wordpiece models (one CJK char == one token).

    Lines are greedily packed into parts within *max_chars* characters; a single
    overlong line is hard-cut at character boundaries.
    """
    if len(text) <= max_chars:
        return [text]
    out: list[str] = []
    for part in _pack_lines_by_chars(text, max_chars):
        if len(part) <= max_chars:
            out.append(part)
        else:
            out.extend(part[i : i + max_chars] for i in range(0, len(part), max_chars))
    return out


def _pack_lines_by_chars(text: str, max_chars: int) -> list[str]:
    """Greedily pack lines into parts that each fit *max_chars* characters.

    Markdown header lines (``# ...``) always start a new part so a section heading
    stays aligned with its content instead of being buried mid-chunk. Lines inside
    ````` ``` ````` code fences never trigger the header split (mirroring
    SmartMarkdownHeaderTextSplitter's code exclusion). A single overlong line is
    still hard-cut downstream by _split_by_character_budget.
    """
    parts: list[str] = []
    current: list[str] = []
    current_len = 0
    in_code_block = False
    for line in text.split("\n"):
        if _CODE_FENCE_RE.match(line):
            in_code_block = not in_code_block
        line_len = len(line)
        starts_header = not in_code_block and _HEADER_LINE_RE.match(line) is not None
        if current and (starts_header or current_len + 1 + line_len > max_chars):
            parts.append("\n".join(current))
            current = [line]
            current_len = line_len
        elif current:
            current.append(line)
            current_len += 1 + line_len
        else:
            current = [line]
            current_len = line_len
    if current:
        parts.append("\n".join(current))
    return parts


def _enforce_chunk_budget(text: str, max_tokens: int) -> list[str]:
    if get_token_count(text) <= max_tokens:
        return [text]
    line_parts = _split_by_lines(text, max_tokens)
    if len(line_parts) <= 1 and get_token_count(text) > max_tokens:
        midpoint = max(1, len(text) // 2)
        left = text[:midpoint].strip()
        right = text[midpoint:].strip()
        parts: list[str] = []
        if left:
            parts.extend(_enforce_chunk_budget(left, max_tokens))
        if right:
            parts.extend(_enforce_chunk_budget(right, max_tokens))
        return parts
    out: list[str] = []
    for part in line_parts:
        out.extend(_enforce_chunk_budget(part, max_tokens))
    return out
