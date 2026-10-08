"""ObservationPack long output archival, sliding-window degradation, and paged recall package.

[INPUT]
- None (Public package entrypoint).

[OUTPUT]
- ContentAddressedStore: Immutable content-addressed object store.
- ObservationDegradationPipeline: 2-turn full send window and excerpt placeholder generator.
- ObservationHandle: Descriptive metadata for an archived observation.
- ObservationPage: 1-indexed line slice of an observation.
- ObservationPackConfig: Configuration for thresholds and excerpt budgets.
- ObservationPackPagedRecallAndLongOutputHandleArchivalSuite: Central facade suite.
- ObservationRecallTool: Meta-tool for paged recall by obs ID.
- ObservationSendState: Send count state tracker.
- PackBatchResult: Batch message transformation result.
- TransformDecision: Individual observation transformation verdict.

[POS]
Package facade for NVIDIA SoL-Pi inspired ObservationPack components.
"""

from __future__ import annotations

from .content_addressed_store import ContentAddressedStore
from .observation_degradation_pipeline import ObservationDegradationPipeline
from .observation_pack_suite import (
    ObservationPackPagedRecallAndLongOutputHandleArchivalSuite,
)
from .observation_pack_types import (
    ObservationHandle,
    ObservationPackConfig,
    ObservationPage,
    ObservationSendState,
    PackBatchResult,
    TransformDecision,
)
from .observation_recall_tool import ObservationRecallTool

__all__ = [
    "ContentAddressedStore",
    "ObservationDegradationPipeline",
    "ObservationHandle",
    "ObservationPackConfig",
    "ObservationPackPagedRecallAndLongOutputHandleArchivalSuite",
    "ObservationPage",
    "ObservationRecallTool",
    "ObservationSendState",
    "PackBatchResult",
    "TransformDecision",
]
