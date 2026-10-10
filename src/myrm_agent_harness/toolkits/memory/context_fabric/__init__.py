"""Cross-Source Work Context Fabric & Project Entity Linker Suite.

[INPUT]
- Re-exports domain models, entity extractors, dynamic linkers, and insight sink engines.

[OUTPUT]
- Public package facade for Item 153 CrossSourceWorkContextFabricAndProjectEntityLinkerSuite.

[POS]
- Root facade for toolkits/memory/context_fabric.
"""

from __future__ import annotations

from .extractor import ContextFabricExtractor
from .linker import ProjectEntityLinker
from .models import (
    EntityMatchResult,
    InsightCandidate,
    InsightSinkRecord,
    ProjectRegistryEntry,
    SourceKind,
    WorkContextEntity,
    WorkEvent,
)
from .sink import InsightSinkEngine

__all__ = [
    "ContextFabricExtractor",
    "EntityMatchResult",
    "InsightCandidate",
    "InsightSinkEngine",
    "InsightSinkRecord",
    "ProjectEntityLinker",
    "ProjectRegistryEntry",
    "SourceKind",
    "WorkContextEntity",
    "WorkEvent",
]
