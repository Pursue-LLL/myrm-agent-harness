"""Rigidly evaluates and asserts vector dimension consistency before store operations.

[INPUT]
- toolkits.memory.vector_preflight.types::DimensionIntegrityReport, PreflightHealthStatus (POS: Typed data
  contracts for the vector preflight subsystem.)

[OUTPUT]
- DimensionIntegrityProbe: Rigidly evaluates and asserts vector dimension consistency before store
  operations.

[POS]
Rigidly evaluates and asserts vector dimension consistency before store operations.
"""

import logging
from collections.abc import Callable

from .types import DimensionIntegrityReport, PreflightHealthStatus

logger = logging.getLogger(__name__)


class DimensionIntegrityProbe:
    """Rigidly evaluates and asserts vector dimension consistency before store operations."""

    @classmethod
    def verify_dimension_integrity(
        cls,
        actual_dims: int,
        expected_dims: int,
        embedder_name: str = "configured_embedder",
        collection_name: str = "memory_collection",
    ) -> DimensionIntegrityReport:
        """Compare actual embedding dimensions against expected collection schema."""
        if actual_dims <= 0 or expected_dims <= 0:
            diagnosis = (
                f"Invalid dimension configuration: actual={actual_dims}, expected={expected_dims}. "
                "Dimensions must be strictly positive integers."
            )
            return DimensionIntegrityReport(
                is_valid=False,
                actual_dims=actual_dims,
                expected_dims=expected_dims,
                status=PreflightHealthStatus.INVALID_CONFIGURATION,
                diagnosis=diagnosis,
                suggested_action="Specify valid positive integer dimensions in your embedding model and collection settings.",
            )

        if actual_dims == expected_dims:
            diagnosis = (
                f"Embedding vector dimension ({actual_dims}) from '{embedder_name}' "
                f"perfectly matches target collection '{collection_name}'."
            )
            return DimensionIntegrityReport(
                is_valid=True,
                actual_dims=actual_dims,
                expected_dims=expected_dims,
                status=PreflightHealthStatus.HEALTHY,
                diagnosis=diagnosis,
                suggested_action="",
            )

        # Dimension mismatch detected
        diagnosis = (
            f"Embedding dimension mismatch detected: embedder '{embedder_name}' outputs {actual_dims} dims, "
            f"whereas target collection '{collection_name}' expects {expected_dims} dims."
        )
        suggested_action = (
            f"Recreate collection '{collection_name}' with vector size {actual_dims}, or change the embedding "
            f"model to match {expected_dims} dimensions (e.g. OpenAI text-embedding-3-small=1536, BGE-large=1024, Qwen3=2560)."
        )
        logger.error("DimensionIntegrityProbe blocked: %s", diagnosis)

        return DimensionIntegrityReport(
            is_valid=False,
            actual_dims=actual_dims,
            expected_dims=expected_dims,
            status=PreflightHealthStatus.MISMATCH_BLOCKED,
            diagnosis=diagnosis,
            suggested_action=suggested_action,
        )

    @classmethod
    def sample_and_verify(
        cls,
        embed_fn: Callable[[str], list[float]],
        expected_dims: int,
        sample_text: str = "preflight_probe",
        embedder_name: str = "configured_embedder",
        collection_name: str = "memory_collection",
    ) -> DimensionIntegrityReport:
        """Dynamically execute embedding function on probe sample and verify vector dimensions."""
        try:
            sample_vector = embed_fn(sample_text)
            actual_dims = len(sample_vector)
            return cls.verify_dimension_integrity(
                actual_dims=actual_dims,
                expected_dims=expected_dims,
                embedder_name=embedder_name,
                collection_name=collection_name,
            )
        except Exception as exc:
            diagnosis = f"Failed to sample embedding vector from '{embedder_name}': {exc}"
            logger.exception(diagnosis)
            return DimensionIntegrityReport(
                is_valid=False,
                actual_dims=0,
                expected_dims=expected_dims,
                status=PreflightHealthStatus.INVALID_CONFIGURATION,
                diagnosis=diagnosis,
                suggested_action="Verify embedding provider connectivity, credentials, and API endpoint availability.",
            )
