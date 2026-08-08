"""Tests for embed window policy and embed-budget splitting."""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.retriever.embedding.cloud_embedding import CloudEmbedding
from myrm_agent_harness.toolkits.retriever.embedding.window_policy import (
    EmbedInputTooLargeError,
    EmbedWindowPolicy,
    resolve_embed_window_policy,
)
from myrm_agent_harness.toolkits.retriever.splitter.embed_budget import split_for_embedding
from myrm_agent_harness.toolkits.wiki.retrieval.vector_chunks import collapse_vector_hits
from myrm_agent_harness.utils.text_utils import get_token_count


class TestEmbedWindowPolicy:
    def test_openai_model_window(self) -> None:
        policy = EmbedWindowPolicy.for_model("text-embedding-3-small")
        assert policy.max_input_tokens == 8191
        assert policy.effective_chunk_tokens < policy.max_input_tokens

    def test_unknown_model_conservative_default(self) -> None:
        policy = EmbedWindowPolicy.for_model("unknown-local-embed")
        assert policy.max_input_tokens == 512

    def test_cloud_embedding_exposes_input_limit(self) -> None:
        service = CloudEmbedding(model="text-embedding-3-small", api_key="test")
        assert service.input_token_limit == 8191
        assert resolve_embed_window_policy(service).max_input_tokens == 8191


class TestSplitForEmbedding:
    def test_short_text_single_chunk(self) -> None:
        policy = EmbedWindowPolicy.for_model("text-embedding-3-small")
        text = "Short wiki truth section."
        chunks = split_for_embedding(text, policy)
        assert chunks == [text]

    def test_long_text_multiple_chunks(self) -> None:
        policy = EmbedWindowPolicy.for_model("BAAI/bge-large-zh-v1.5")
        paragraphs = [
            "## Section {}\n\n{}".format(
                i,
                "Detailed engineering notes about module {} with extra context.".format(i) * 20,
            )
            for i in range(20)
        ]
        text = "\n\n".join(paragraphs)
        chunks = split_for_embedding(text, policy)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert get_token_count(chunk) <= policy.effective_chunk_tokens


class TestCollapseVectorHits:
    def test_keeps_best_score_per_concept(self) -> None:
        hits = [
            ("Concept/A", 0.4),
            ("Concept/A", 0.9),
            ("Concept/B", 0.7),
        ]
        collapsed = collapse_vector_hits(hits)
        assert collapsed == [("Concept/A", 0.9), ("Concept/B", 0.7)]


class TestCloudEmbeddingValidation:
    @pytest.mark.asyncio
    async def test_rejects_oversized_single_input(self) -> None:
        service = CloudEmbedding(model="BAAI/bge-large-zh-v1.5", api_key="test")
        huge = "token " * 2000
        with pytest.raises(EmbedInputTooLargeError):
            await service.embed(huge)
