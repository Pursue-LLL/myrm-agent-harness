"""Embedding input window policy — model max tokens SSOT for embed-time chunking.

[INPUT]
utils.text_utils::get_token_count (POS: o200k token counting)

[OUTPUT]
EmbedWindowPolicy: effective chunk budget derived from provider max input tokens
EmbedInputTooLargeError: fail-loud when text exceeds embed window after split
resolve_embed_window_policy(): derive policy from an embedding service instance
token_counter_for_model(): model-family counter for fail-loud window checks

[POS]
Embedding transport policy layer. Keeps ingest/index chunk budgets aligned with the
active embedding model without coupling to wiki or memory business logic.

Budget semantics:
- BPE models (o200k-compatible): ``effective_chunk_budget`` is an o200k token
  budget at the standard 0.9 margin (0.5 for small windows <= 1024).
- Wordpiece models (bge/bce/nomic): ``effective_chunk_budget`` is a character-count
  budget, because their tokenizers count one CJK char as one token while o200k
  undercounts CJK (~2 chars/token); split_for_embedding chunks on characters for
  these models. Small windows stay at 0.5; bge-m3 (XLM-R 250k, measured char/token
  < 1 across zh/ja/ko/en) uses 0.9.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from myrm_agent_harness.utils.text_utils import get_token_count

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol

DEFAULT_MAX_INPUT_TOKENS = 512
# Safety margins for deriving the effective chunk budget.
# BPE tokenizers (o200k, cl100k, Qwen ...) count ~1.5 CJK chars per token and are
# roughly compatible with get_token_count; wordpiece models (BERT/XLM: bge/bce/nomic)
# count 1 CJK char per token, so their budget is a character count and must not be
# derived from o200k or the provider silently truncates CJK input.
SAFETY_MARGIN = 0.9
CJK_WORDPIECE_SAFETY_MARGIN = 0.5
SMALL_WINDOW_MAX_TOKENS = 1024
# bge-m3 (XLM-R 250k) has measured char/token < 1 across zh/ja/ko/en, so its
# character-count budget can use the standard margin without risking window overflow.
_XLM_R_SAFE_WORDPIECE_MODELS = frozenset({"bge-m3"})

KNOWN_MODEL_MAX_INPUT_TOKENS: dict[str, int] = {
    # OpenAI
    "text-embedding-3-small": 8191,
    "text-embedding-3-large": 8191,
    "text-embedding-ada-002": 8191,
    # Voyage AI
    "voyage-3": 32000,
    "voyage-3-lite": 32000,
    "voyage-code-3": 32000,
    # Jina AI
    "jina-embeddings-v3": 8192,
    "jina-embeddings-v2-base-en": 8192,
    # SiliconFlow / open models commonly configured in Settings
    "BAAI/bge-large-zh-v1.5": 512,
    "netease-youdao/bce-embedding-base_v1": 512,
    "BAAI/bge-m3": 8192,
    "Pro/BAAI/bge-m3": 8192,
    "Qwen/Qwen3-Embedding-8B": 8192,
    "Qwen/Qwen3-Embedding-4B": 8192,
    "nomic-embed-text": 2048,
    # sentence-transformers / HF wordpiece models commonly self-hosted
    "all-MiniLM-L6-v2": 256,
    "all-MiniLM-L12-v2": 256,
    "paraphrase-MiniLM-L6-v2": 256,
    "paraphrase-multilingual-MiniLM-L12-v2": 128,
    "multilingual-e5-small": 512,
    "multilingual-e5-base": 512,
    "multilingual-e5-large": 512,
    "jina-embeddings-v2-base-zh": 8192,
}


class EmbedInputTooLargeError(Exception):
    """Raised when text still exceeds the embedding model window after force-split."""

    def __init__(
        self,
        *,
        token_count: int,
        limit: int,
        model: str | None = None,
        parent_key: str | None = None,
    ) -> None:
        self.token_count = token_count
        self.limit = limit
        self.model = model
        self.parent_key = parent_key
        model_label = model or "embedding model"
        scope = f" for '{parent_key}'" if parent_key else ""
        super().__init__(
            f"Embedding input {token_count} tokens exceeds {model_label} limit {limit}{scope}"
        )


@dataclass(frozen=True, slots=True)
class EmbedWindowPolicy:
    """Hard embed budget with safety margin reserved for provider overhead.

    ``effective_chunk_budget`` is denominated in the model family's own budget
    unit: an o200k token count for BPE models, a character count for wordpiece
    models (one CJK char == one token).
    """

    max_input_tokens: int
    effective_chunk_budget: int
    model: str | None = None

    @classmethod
    def for_model(cls, model: str) -> EmbedWindowPolicy:
        max_tokens = _lookup_max_input_tokens(model)
        effective = max(32, int(max_tokens * _safety_margin_for(max_tokens, model)))
        return cls(max_input_tokens=max_tokens, effective_chunk_budget=effective, model=model or None)

    @classmethod
    def from_max_tokens(cls, max_input_tokens: int, *, model: str | None = None) -> EmbedWindowPolicy:
        safe_max = max(32, max_input_tokens)
        effective = max(32, int(safe_max * _safety_margin_for(safe_max, model)))
        return cls(max_input_tokens=safe_max, effective_chunk_budget=effective, model=model)


# CJK scripts that BERT/XLM wordpiece tokenizers count as one token per char.
# o200k BPE undercounts these (1 token ≈ 2 chars for zh/ja/ko), so fail-loud
# validation must count them 1:1 instead of folding them into the latin ratio.
# U+3000-303F (CJK punctuation) and U+FF00-FFEF (fullwidth forms such as ！？）
# are also single-token; counting them at the 1/4 latin ratio would undercount
# punctuation-heavy CJK text.
_CJK_WORDPIECE_RANGES: tuple[tuple[int, int], ...] = (
    (0x3000, 0x303F),  # CJK Symbols and Punctuation
    (0x4E00, 0x9FFF),  # CJK Unified Ideographs
    (0x3400, 0x4DBF),  # CJK Extension A
    (0x3040, 0x309F),  # Hiragana
    (0x30A0, 0x30FF),  # Katakana
    (0xAC00, 0xD7AF),  # Hangul Syllables
    (0xF900, 0xFAFF),  # CJK Compatibility
    (0xFF00, 0xFFEF),  # Fullwidth Forms (！？（） etc.)
)


def _is_cjk_wordpiece_char(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_WORDPIECE_RANGES)


def is_cjk_wordpiece_model(model: str | None) -> bool:
    """Whether the model tokenizes CJK as wordpieces (BERT/XLM family).

    bge/bce/nomic/minilm/e5/paraphrase/jina-embeddings-v2/v3 are built on
    BERT/XLM wordpiece vocabularies where one CJK char maps to one token, while
    get_token_count uses o200k BPE where one token spans ~2 CJK chars. Without a
    conservative margin the o200k budget undercounts the real provider input and
    text silently truncates.
    """
    if not model:
        return False
    base = model.rsplit("/", 1)[-1].lower()
    return (
        base.startswith(("bge", "bce", "nomic"))
        or "minilm" in base
        or base.startswith("multilingual-e5")
        or base.startswith("paraphrase-")
        or base.startswith(("jina-embeddings-v2", "jina-embeddings-v3"))
    )


def estimate_wordpiece_tokens(text: str) -> int:
    """Conservative wordpiece token estimate for BERT/XLM embedding models.

    These tokenizers count one in-vocabulary CJK char (Han, Hiragana, Katakana,
    Hangul and the CJK extension/compatibility blocks) as one token, and latin/other
    scripts at roughly 4 chars per token (rounded up). The estimate is an upper bound
    (>= real tokens) for in-vocabulary text, so it is safe for fail-loud window
    validation where o200k undercounts CJK input. Out-of-vocabulary scripts (e.g.
    Hangul on a Chinese BERT such as bge-large-zh, measured ~1.86 tokens/char) can
    exceed 1 token per char; that headroom is absorbed by the conservative
    character-count chunk budget (0.5 margin), not by this estimate.
    """
    if not text:
        return 0
    cjk_chars = sum(1 for ch in text if _is_cjk_wordpiece_char(ch))
    other_chars = len(text) - cjk_chars
    return cjk_chars + (other_chars + 3) // 4


def token_counter_for_model(model: str | None) -> Callable[[str], int]:
    """Return the token-counting callable matching a model's budget unit.

    Wordpiece models (bge/bce/nomic) count one CJK char as one token via
    ``estimate_wordpiece_tokens``; BPE models count tiktoken o200k tokens via
    ``get_token_count``. Every consumer of the embed budget must use this so
    fail-loud window checks never undercount CJK input (o200k ~2 chars/token).
    """
    if is_cjk_wordpiece_model(model):
        return estimate_wordpiece_tokens
    return get_token_count


def _safety_margin_for(max_input_tokens: int, model: str | None) -> float:
    """Return the chunk-budget safety margin for a model window.

    Wordpiece models (bge/bce/nomic) budget on character count (one CJK char == one
    token): small windows stay at 0.5, while bge-m3 (XLM-R 250k, measured char/token
    < 1 across zh/ja/ko/en) can use the standard 0.9. BPE models budget on o200k
    tokens and keep 0.9 except for small windows (<=1024).
    """
    if is_cjk_wordpiece_model(model):
        base = model.rsplit("/", 1)[-1].lower()
        if max_input_tokens > SMALL_WINDOW_MAX_TOKENS and base in _XLM_R_SAFE_WORDPIECE_MODELS:
            return SAFETY_MARGIN
        return CJK_WORDPIECE_SAFETY_MARGIN
    if max_input_tokens <= SMALL_WINDOW_MAX_TOKENS:
        return CJK_WORDPIECE_SAFETY_MARGIN
    return SAFETY_MARGIN


@runtime_checkable
class SupportsInputTokenLimit(Protocol):
    @property
    def input_token_limit(self) -> int: ...


def _lookup_max_input_tokens(model: str) -> int:
    if not model:
        return DEFAULT_MAX_INPUT_TOKENS
    variants = [model]
    if "/" in model:
        variants.append(model.split("/", 1)[1])
        variants.append(model.rsplit("/", 1)[-1])
    for variant in variants:
        if variant in KNOWN_MODEL_MAX_INPUT_TOKENS:
            return KNOWN_MODEL_MAX_INPUT_TOKENS[variant]
    return DEFAULT_MAX_INPUT_TOKENS


def resolve_embed_window_policy(embedding: EmbeddingProtocol) -> EmbedWindowPolicy:
    """Resolve embed window policy from a concrete embedding service."""
    if isinstance(embedding, SupportsInputTokenLimit):
        return EmbedWindowPolicy.from_max_tokens(
            embedding.input_token_limit,
            model=getattr(embedding, "_model", None),
        )
    model = getattr(embedding, "_model", None)
    if isinstance(model, str) and model:
        return EmbedWindowPolicy.for_model(model)
    return EmbedWindowPolicy.for_model("")
