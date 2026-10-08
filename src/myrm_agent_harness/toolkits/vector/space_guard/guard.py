"""Vector space consistency guard implementation.

[POS]
Core pre-flight validation gate ensuring embedding model dimension, base coordinate
space, and distance metric integrity across vector storage operations.

[INPUT]
- datetime, typing
- .models (EmbeddingModelFingerprint, VectorSpaceBaseMismatchError,
  VectorSpaceDimensionMismatchError, VectorSpaceMetadata,
  VectorSpaceMismatchError, VectorSpaceValidationResult)

[OUTPUT]
- VectorSpaceGuard
"""

from __future__ import annotations

from datetime import UTC, datetime

from myrm_agent_harness.toolkits.vector.space_guard.models import (
    EmbeddingModelFingerprint,
    VectorSpaceBaseMismatchError,
    VectorSpaceDimensionMismatchError,
    VectorSpaceMetadata,
    VectorSpaceMismatchError,
    VectorSpaceValidationResult,
)


class VectorSpaceGuard:
    """Pre-flight consistency guard protecting vector collections against heterogeneous contamination."""

    def __init__(self) -> None:
        """Initialize in-memory space registry."""
        self._registry: dict[str, VectorSpaceMetadata] = {}

    def bind_fingerprint(
        self,
        collection: str,
        fingerprint: EmbeddingModelFingerprint,
        total_vectors_indexed: int = 0,
    ) -> VectorSpaceMetadata:
        """Bind or update canonical model fingerprint for a collection."""
        now = datetime.now(UTC)
        meta = VectorSpaceMetadata(
            collection_name=collection,
            fingerprint=fingerprint,
            created_at=now,
            last_validated_at=now,
            total_vectors_indexed=total_vectors_indexed,
        )
        self._registry[collection] = meta
        return meta

    def get_space_metadata(self, collection: str) -> VectorSpaceMetadata | None:
        """Retrieve stored metadata for given collection."""
        return self._registry.get(collection)

    def has_registered_space(self, collection: str) -> bool:
        """Check whether collection has been bound to a model fingerprint."""
        return collection in self._registry

    def remove_space_metadata(self, collection: str) -> bool:
        """Remove collection space registration."""
        if collection in self._registry:
            del self._registry[collection]
            return True
        return False

    def validate_space(
        self,
        collection: str,
        current_fingerprint: EmbeddingModelFingerprint,
        auto_bind_if_empty: bool = False,
    ) -> VectorSpaceValidationResult:
        """Verify runtime embedding model against collection space fingerprint.

        Args:
            collection: Target collection name.
            current_fingerprint: Runtime model fingerprint.
            auto_bind_if_empty: If True, binds automatically on first contact.

        Returns:
            VectorSpaceValidationResult containing diagnostic status and recommendation.
        """
        registered = self.get_space_metadata(collection)
        if registered is None:
            if auto_bind_if_empty:
                self.bind_fingerprint(collection, current_fingerprint)
                return VectorSpaceValidationResult(
                    is_valid=True,
                    status="consistent",
                    message=f"Collection '{collection}' initialized with model {current_fingerprint.model_name}",
                    expected_fingerprint=current_fingerprint,
                    current_fingerprint=current_fingerprint,
                    recommended_action="proceed",
                )
            return VectorSpaceValidationResult(
                is_valid=False,
                status="uninitialized",
                message=f"Collection '{collection}' has no registered embedding space metadata",
                expected_fingerprint=None,
                current_fingerprint=current_fingerprint,
                recommended_action="initialize_space",
            )

        expected = registered.fingerprint
        compatible, reason = expected.is_compatible_with(current_fingerprint)

        if compatible:
            registered.last_validated_at = datetime.now(UTC)
            return VectorSpaceValidationResult(
                is_valid=True,
                status="consistent",
                message=f"Collection '{collection}' matches model {current_fingerprint.model_name}",
                expected_fingerprint=expected,
                current_fingerprint=current_fingerprint,
                recommended_action="proceed",
            )

        # Distinguish between dimension mismatch and model base drift
        if expected.vector_dimension != current_fingerprint.vector_dimension:
            return VectorSpaceValidationResult(
                is_valid=False,
                status="dimension_mismatch",
                message=reason,
                expected_fingerprint=expected,
                current_fingerprint=current_fingerprint,
                recommended_action="reindex_required",
            )

        return VectorSpaceValidationResult(
            is_valid=False,
            status="model_base_mismatch",
            message=reason,
            expected_fingerprint=expected,
            current_fingerprint=current_fingerprint,
            recommended_action="reindex_required",
        )

    def enforce_space_safety(
        self,
        collection: str,
        current_fingerprint: EmbeddingModelFingerprint,
        auto_bind_if_empty: bool = False,
    ) -> None:
        """Strict pre-flight enforcement gate. Raises strongly typed exceptions on mismatch.

        Raises:
            VectorSpaceDimensionMismatchError: On dimension divergence.
            VectorSpaceBaseMismatchError: On model provider or name divergence.
            VectorSpaceMismatchError: On missing or uninitialized space metadata.
        """
        result = self.validate_space(
            collection, current_fingerprint, auto_bind_if_empty=auto_bind_if_empty
        )
        if result.is_valid:
            return

        if result.status == "dimension_mismatch":
            raise VectorSpaceDimensionMismatchError(
                result.message,
                expected=result.expected_fingerprint,
                actual=result.current_fingerprint,
            )
        if result.status == "model_base_mismatch":
            raise VectorSpaceBaseMismatchError(
                result.message,
                expected=result.expected_fingerprint,
                actual=result.current_fingerprint,
            )

        raise VectorSpaceMismatchError(
            result.message,
            expected=result.expected_fingerprint,
            actual=result.current_fingerprint,
        )

    def get_search_fallback_decision(
        self, result: VectorSpaceValidationResult
    ) -> dict[str, str]:
        """Generate safe fallback routing instructions when vector space is incompatible."""
        if result.is_valid:
            return {
                "execution_mode": "dense_vector",
                "reason": "Vector space is consistent and validated",
                "recommended_action": "proceed",
            }

        return {
            "execution_mode": "keyword_fts5_fallback",
            "reason": (
                f"Vector space blocked: {result.message}. "
                "Falling back to keyword FTS to prevent memory contamination."
            ),
            "recommended_action": result.recommended_action,
        }
