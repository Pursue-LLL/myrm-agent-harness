"""Embedding input window policy — model max tokens SSOT for embed-time chunking.

[INPUT]
(none)

[OUTPUT]
EmbedWindowPolicy: effective chunk budget derived from provider max input tokens
EmbedInputTooLargeError: fail-loud when text exceeds embed window after split
resolve_embed_window_policy(): derive policy from an embedding service instance

[POS]
Embedding transport policy layer. Keeps ingest/index chunk budgets aligned with the
active embedding model without coupling to wiki or memory business logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol

DEFAULT_MAX_INPUT_TOKENS = 512
SAFETY_MARGIN = 0.9

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
    """Hard embed budget with safety margin reserved for provider overhead."""

    max_input_tokens: int
    effective_chunk_tokens: int
    model: str | None = None

    @classmethod
    def for_model(cls, model: str) -> EmbedWindowPolicy:
        max_tokens = _lookup_max_input_tokens(model)
        effective = max(32, int(max_tokens * SAFETY_MARGIN))
        return cls(max_input_tokens=max_tokens, effective_chunk_tokens=effective, model=model or None)

    @classmethod
    def from_max_tokens(cls, max_input_tokens: int, *, model: str | None = None) -> EmbedWindowPolicy:
        safe_max = max(32, max_input_tokens)
        effective = max(32, int(safe_max * SAFETY_MARGIN))
        return cls(max_input_tokens=safe_max, effective_chunk_tokens=effective, model=model)


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
