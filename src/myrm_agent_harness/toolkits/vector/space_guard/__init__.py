"""Vector space consistency guard package.

[POS]
Embedded vector space validation package safeguarding against heterogeneous
embedding model base corruption and dimensional divergence.

[INPUT]
- .models (EmbeddingModelFingerprint, ReindexStatusReport, VectorSpaceBaseMismatchError,
  VectorSpaceDimensionMismatchError, VectorSpaceMetadata, VectorSpaceMismatchError,
  VectorSpaceValidationResult)
- .guard (VectorSpaceGuard)
- .reindexer (VectorSpaceReindexer)

[OUTPUT]
- EmbeddingModelFingerprint, ReindexStatusReport, VectorSpaceBaseMismatchError,
  VectorSpaceDimensionMismatchError, VectorSpaceGuard, VectorSpaceMetadata,
  VectorSpaceMismatchError, VectorSpaceReindexer, VectorSpaceValidationResult
"""

from myrm_agent_harness.toolkits.vector.space_guard.guard import VectorSpaceGuard
from myrm_agent_harness.toolkits.vector.space_guard.models import (
    EmbeddingModelFingerprint,
    ReindexStatusReport,
    VectorSpaceBaseMismatchError,
    VectorSpaceDimensionMismatchError,
    VectorSpaceMetadata,
    VectorSpaceMismatchError,
    VectorSpaceValidationResult,
)
from myrm_agent_harness.toolkits.vector.space_guard.reindexer import (
    VectorSpaceReindexer,
)

__all__ = [
    "EmbeddingModelFingerprint",
    "ReindexStatusReport",
    "VectorSpaceBaseMismatchError",
    "VectorSpaceDimensionMismatchError",
    "VectorSpaceGuard",
    "VectorSpaceMetadata",
    "VectorSpaceMismatchError",
    "VectorSpaceReindexer",
    "VectorSpaceValidationResult",
]
