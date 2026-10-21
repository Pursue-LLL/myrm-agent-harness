"""Reasoning strategy package.

[INPUT]
- langchain_core.messages (POS: Message models)

[OUTPUT]
- ReasoningAnchor: Core reasoning anchor data model
- extract_raw_reasoning: Provider-agnostic reasoning content extraction
- extract_reasoning_anchors: Heuristic decision anchor extraction
- SessionAnchorLedger: Immutable session-scoped reasoning ledger

[POS]
Strategy sub-package for extracting, tracking, and preserving immutable reasoning anchors.
"""

from .anchor_extractor import ReasoningAnchor, extract_raw_reasoning, extract_reasoning_anchors
from .anchor_ledger import SessionAnchorLedger

__all__ = [
    "ReasoningAnchor",
    "SessionAnchorLedger",
    "extract_raw_reasoning",
    "extract_reasoning_anchors",
]
