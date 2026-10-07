"""[POS]: src/myrm_agent_harness/toolkits/memory/noise_free_extractor/__init__.py
[INPUT]: Tool noise filter, PII safety gateway, epoch manager, and unified extractor modules.
[OUTPUT]: Public exports for tool-noise-free async memory extraction and purge generation suite.

Reference: Anthropic Commerce Agents (commerce_common/memory.py).
Provides:
- ToolNoiseFilter: Strips tool receipts & code output from memory extraction prompts;
- PIISafetyGateway: Code-level regex safety filters for cards, IBANs, credentials, and IDs;
- PurgeGenerationEpochManager: Monotonic purge generation epoch fencing preventing ghost memory resurrection;
- NoiseFreeAsyncMemoryExtractor: End-to-end extraction orchestrator.
"""

from .epoch_manager import PurgeGenerationEpochManager
from .extractor import NoiseFreeAsyncMemoryExtractor
from .noise_filter import ToolNoiseFilter
from .pii_gateway import PIISafetyGateway
from .types import (
    ConversationTurn,
    ExtractedFactCandidate,
    NoiseFreeConfig,
    PIIViolationDetail,
    PurgeEpochStatus,
    SanitizedExtractionResult,
    ToolStrippedMessage,
)

__all__ = [
    "ConversationTurn",
    "ExtractedFactCandidate",
    "NoiseFreeAsyncMemoryExtractor",
    "NoiseFreeConfig",
    "PIISafetyGateway",
    "PIIViolationDetail",
    "PurgeEpochStatus",
    "PurgeGenerationEpochManager",
    "SanitizedExtractionResult",
    "ToolNoiseFilter",
    "ToolStrippedMessage",
]
