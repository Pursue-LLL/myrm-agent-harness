"""[INPUT]
- .models: UiVariant, UiVariantStyle, VisualAnnotation, VisualContract
- .alignment_engine: UiDesignVisualAlignmentEngine

[OUTPUT]
- Public facade exports for UI visual design alignment toolkit

[POS]
Harness framework layer facade for Item 39 P0.
"""

from .alignment_engine import UiDesignVisualAlignmentEngine
from .models import (
    UiVariant,
    UiVariantStyle,
    VisualAnnotation,
    VisualContract,
)

__all__ = [
    "UiDesignVisualAlignmentEngine",
    "UiVariant",
    "UiVariantStyle",
    "VisualAnnotation",
    "VisualContract",
]
