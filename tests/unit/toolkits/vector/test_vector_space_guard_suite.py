"""Unit test suite for embedding model dimension and vector space guard.

[POS]
Unit test verifying model fingerprint determinism, pre-flight space consistency checks,
dimension mismatch hard gates, model base drift defense, and graceful fallback decisions.

[INPUT]
- pytest
- myrm_agent_harness.toolkits.vector (
    EmbeddingModelFingerprint,
    ReindexStatusReport,
    VectorSpaceBaseMismatchError,
    VectorSpaceDimensionMismatchError,
    VectorSpaceGuard,
    VectorSpaceMismatchError,
    VectorSpaceReindexer,
    VectorSpaceValidationResult,
  )

[OUTPUT]
- Test functions covering vector space guard capabilities.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.toolkits.vector import (
    EmbeddingModelFingerprint,
    VectorSpaceBaseMismatchError,
    VectorSpaceDimensionMismatchError,
    VectorSpaceGuard,
    VectorSpaceMismatchError,
    VectorSpaceReindexer,
    VectorSpaceValidationResult,
)


def test_fingerprint_deterministic_hash() -> None:
    """Verify deterministic config hash generation across identical model parameters."""
    fp1 = EmbeddingModelFingerprint(
        provider_id="openai",
        model_name="text-embedding-3-small",
        vector_dimension=1536,
        metric_type="cosine",
    )
    fp2 = EmbeddingModelFingerprint(
        provider_id="OpenAI",  # Case insensitive normalization
        model_name="TEXT-EMBEDDING-3-SMALL",
        vector_dimension=1536,
        metric_type="cosine",
    )
    assert fp1.config_hash != ""
    assert fp1.config_hash == fp2.config_hash


def test_space_compatibility_matching() -> None:
    """Verify exact match returns compatibility."""
    guard = VectorSpaceGuard()
    coll = "general_knowledge"
    canonical_fp = EmbeddingModelFingerprint(
        provider_id="openai",
        model_name="text-embedding-3-small",
        vector_dimension=1536,
    )
    guard.bind_fingerprint(coll, canonical_fp)

    # 1. Matching fingerprint
    result = guard.validate_space(coll, canonical_fp)
    assert result.is_valid is True
    assert result.status == "consistent"
    assert result.recommended_action == "proceed"

    # Enforce should not raise
    guard.enforce_space_safety(coll, canonical_fp)


def test_dimension_mismatch_enforcement_raises() -> None:
    """Verify dimension mismatch triggers dimension_mismatch status and strongly typed error."""
    guard = VectorSpaceGuard()
    coll = "docs_index"
    guard.bind_fingerprint(
        coll,
        EmbeddingModelFingerprint(
            provider_id="openai",
            model_name="text-embedding-3-small",
            vector_dimension=1536,
        ),
    )

    divergent_dim_fp = EmbeddingModelFingerprint(
        provider_id="ollama",
        model_name="bge-m3",
        vector_dimension=1024,
    )

    # 1. Validation check
    val = guard.validate_space(coll, divergent_dim_fp)
    assert val.is_valid is False
    assert val.status == "dimension_mismatch"
    assert val.recommended_action == "reindex_required"

    # 2. Hard gate enforcement raises VectorSpaceDimensionMismatchError
    with pytest.raises(VectorSpaceDimensionMismatchError) as exc_info:
        guard.enforce_space_safety(coll, divergent_dim_fp)
    assert "Dimension mismatch" in str(exc_info.value)


def test_model_base_mismatch_enforcement_raises() -> None:
    """Verify identical dimension but different model base triggers base drift error."""
    guard = VectorSpaceGuard()
    coll = "codebase_vectors"
    guard.bind_fingerprint(
        coll,
        EmbeddingModelFingerprint(
            provider_id="openai",
            model_name="text-embedding-ada-002",
            vector_dimension=1536,
        ),
    )

    heterogeneous_fp = EmbeddingModelFingerprint(
        provider_id="cohere",
        model_name="embed-english-v3.0",
        vector_dimension=1536,  # Identical dimension!
    )

    # 1. Validation check
    val = guard.validate_space(coll, heterogeneous_fp)
    assert val.is_valid is False
    assert val.status == "model_base_mismatch"
    assert val.recommended_action == "reindex_required"

    # 2. Hard gate enforcement raises VectorSpaceBaseMismatchError
    with pytest.raises(VectorSpaceBaseMismatchError) as exc_info:
        guard.enforce_space_safety(coll, heterogeneous_fp)
    assert "Model base mismatch" in str(exc_info.value)


def test_uninitialized_space_and_auto_bind() -> None:
    """Verify uninitialized collection behavior and auto_bind flag."""
    guard = VectorSpaceGuard()
    coll = "fresh_collection"
    runtime_fp = EmbeddingModelFingerprint(
        provider_id="openai",
        model_name="text-embedding-3-small",
        vector_dimension=1536,
    )

    # 1. Without auto-bind
    val = guard.validate_space(coll, runtime_fp, auto_bind_if_empty=False)
    assert val.is_valid is False
    assert val.status == "uninitialized"
    assert val.recommended_action == "initialize_space"

    with pytest.raises(VectorSpaceMismatchError):
        guard.enforce_space_safety(coll, runtime_fp, auto_bind_if_empty=False)

    # 2. With auto-bind
    val_auto = guard.validate_space(coll, runtime_fp, auto_bind_if_empty=True)
    assert val_auto.is_valid is True
    assert val_auto.status == "consistent"
    assert guard.has_registered_space(coll) is True


def test_search_fallback_decision() -> None:
    """Verify fallback decision generation for degraded retrieval."""
    guard = VectorSpaceGuard()
    # Consistent
    valid_res = VectorSpaceValidationResult(
        is_valid=True,
        status="consistent",
        message="OK",
        recommended_action="proceed",
    )
    fallback_ok = guard.get_search_fallback_decision(valid_res)
    assert fallback_ok["execution_mode"] == "dense_vector"

    # Inconsistent
    invalid_res = VectorSpaceValidationResult(
        is_valid=False,
        status="dimension_mismatch",
        message="Expected 1536, got 1024",
        recommended_action="reindex_required",
    )
    fallback_degraded = guard.get_search_fallback_decision(invalid_res)
    assert fallback_degraded["execution_mode"] == "keyword_fts5_fallback"
    assert "Falling back to keyword FTS" in fallback_degraded["reason"]


@pytest.mark.asyncio
async def test_reindexer_pipeline() -> None:
    """Verify safe vector space migration with VectorSpaceReindexer."""
    guard = VectorSpaceGuard()
    coll = "migrating_collection"
    old_fp = EmbeddingModelFingerprint(
        provider_id="openai",
        model_name="text-embedding-ada-002",
        vector_dimension=1536,
    )
    guard.bind_fingerprint(coll, old_fp)

    reindexer = VectorSpaceReindexer(guard)
    target_fp = EmbeddingModelFingerprint(
        provider_id="ollama",
        model_name="bge-m3",
        vector_dimension=1024,
    )

    # Mock embedder that returns 1024-dim vectors
    def dummy_embedder(items: list[str]) -> list[list[float]]:
        return [[0.1] * 1024 for _ in items]

    report = await reindexer.execute_reindex(
        collection=coll,
        target_fingerprint=target_fp,
        items=["Memory 1", "Memory 2"],
        embedder=dummy_embedder,
    )

    assert report.status == "completed"
    assert report.reindexed_count == 2
    assert report.target_fingerprint.vector_dimension == 1024

    # Space in guard must now be updated
    meta = guard.get_space_metadata(coll)
    assert meta is not None
    assert meta.fingerprint.model_name == "bge-m3"
    assert meta.fingerprint.vector_dimension == 1024
