"""Tests for wiki compile embed failure policy."""

from __future__ import annotations

from myrm_agent_harness.toolkits.retriever.embedding.window_policy import EmbedInputTooLargeError
from myrm_agent_harness.toolkits.wiki.pipeline.resilience.failure_policy import (
    EMBED_WINDOW_VIOLATION,
    resolve_embed_failure,
)


class TestResolveEmbedFailure:
    def test_maps_to_embed_window_violation(self) -> None:
        exc = EmbedInputTooLargeError(
            token_count=900,
            limit=512,
            model="BAAI/bge-large-zh-v1.5",
            parent_key="contracts/overview",
        )
        reason, kind = resolve_embed_failure(exc)
        assert kind == EMBED_WINDOW_VIOLATION
        assert "900" in reason
        assert "512" in reason
        assert "contracts/overview" in reason

    def test_sanitized_reason_has_no_api_key_patterns(self) -> None:
        exc = EmbedInputTooLargeError(token_count=100, limit=50, model="test-model")
        reason, _kind = resolve_embed_failure(exc)
        assert "sk-" not in reason.lower()
