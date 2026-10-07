"""Public facade of the dual track extraction subsystem.

[INPUT]
- toolkits.memory.dual_track_extraction.classifier::DualTrackSemanticClassifier (POS: Classifies incoming
  text into Fact, Procedural Rule, Dual-Track, or No-Signal.)
- toolkits.memory.dual_track_extraction.gateway::DualTrackExtractionGateway (POS: Adaptive extraction and
  routing gateway defending against silent drop defects.)
- toolkits.memory.dual_track_extraction.types::ExtractedProceduralRule, ExtractedUserFact,
  ExtractionDestiny, ExtractionDestinyReport, ExtractionTrackKind (POS: Typed data contracts for the dual
  track extraction subsystem.)

[OUTPUT]
- Package facade re-exporting 7 public names: DualTrackExtractionGateway, DualTrackSemanticClassifier,
  ExtractedProceduralRule, ExtractedUserFact, ExtractionDestiny, ExtractionDestinyReport,
  ExtractionTrackKind

[POS]
Public facade of the dual track extraction subsystem.
"""

from .classifier import DualTrackSemanticClassifier
from .gateway import DualTrackExtractionGateway
from .types import (
    ExtractedProceduralRule,
    ExtractedUserFact,
    ExtractionDestiny,
    ExtractionDestinyReport,
    ExtractionTrackKind,
)

__all__ = [
    "DualTrackExtractionGateway",
    "DualTrackSemanticClassifier",
    "ExtractedProceduralRule",
    "ExtractedUserFact",
    "ExtractionDestiny",
    "ExtractionDestinyReport",
    "ExtractionTrackKind",
]
