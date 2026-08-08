"""Force-split text chunks to fit embedding model input windows.

[INPUT]
retriever.embedding.window_policy::EmbedWindowPolicy (POS: embed window SSOT)
retriever.splitter.splitter::TextChunker (POS: markdown-aware chunking)
utils.text_utils::get_token_count (POS: tiktoken counting)

[OUTPUT]
split_for_embedding(): split text so every chunk fits the embed budget

[POS]
Embed-time chunking helper. Used by wiki indexers and memory storage before embed_batch.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.retriever.embedding.window_policy import EmbedWindowPolicy
from myrm_agent_harness.toolkits.retriever.splitter.code_utils import _split_by_lines
from myrm_agent_harness.toolkits.retriever.splitter.splitter import TextChunker
from myrm_agent_harness.utils.text_utils import get_token_count


def split_for_embedding(text: str, policy: EmbedWindowPolicy) -> list[str]:
    """Split *text* into chunks that each fit ``policy.effective_chunk_tokens``."""
    stripped = text.strip()
    if not stripped:
        return []

    if get_token_count(stripped) <= policy.effective_chunk_tokens:
        return [stripped]

    chunker = TextChunker(min_chunk_tokens=min(200, policy.effective_chunk_tokens // 4))
    docs = chunker.chunk_text(
        stripped,
        document_metadata={"title": "embed"},
        max_chunk_tokens=policy.effective_chunk_tokens,
    )
    chunks = [doc.page_content.strip() for doc in docs if doc.page_content.strip()]
    if not chunks:
        chunks = [stripped]

    bounded: list[str] = []
    for chunk in chunks:
        bounded.extend(_enforce_chunk_budget(chunk, policy.effective_chunk_tokens))
    return [part for part in bounded if part.strip()]


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
