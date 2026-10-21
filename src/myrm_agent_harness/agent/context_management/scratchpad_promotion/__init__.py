"""[INPUT]
- ScratchpadDraft, PromotionConfig, SeedDocument, ProjectSeed, ScratchpadPromotionEngine

[OUTPUT]
- Re-exports scratchpad promotion symbols

[POS]
Harness framework layer scratchpad promotion package.
Converts lightweight transient scratchpad drafts into structured project seeds.
"""

from .promotion_engine import (
    ProjectSeed,
    PromotionConfig,
    ScratchpadDraft,
    ScratchpadPromotionEngine,
    SeedDocument,
)

__all__ = [
    "ProjectSeed",
    "PromotionConfig",
    "ScratchpadDraft",
    "ScratchpadPromotionEngine",
    "SeedDocument",
]
