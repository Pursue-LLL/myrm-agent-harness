"""Full dialogue 1,200-word anchor with searchable archive handoff package.

[INPUT]
- None (Package root exports).

[OUTPUT]
- ArchiveSearchResult: Single matching record retrieved from prior immutable session archives.
- ExpandedHandoffAnchor: 1,200-word expanded dialogue skeleton with origin session pointer.
- ExpandedHandoffConfig: Configuration governing word budgets, search limits, and thresholds.
- ExpandedHandoffSuite: Short-hand alias for developer convenience.
- ExpandedSkeletonAnchorBuilder: Synthesizes rich 1,200-word context skeleton preserving decisions and paths.
- FullDialogue1200WordAnchorWithSearchableArchiveHandoffSuite: Unified facade coordinating anchor and searchback.
- HistoricalSessionTurn: Immutable turn snapshot from prior session history.
- SearchableOldSessionArchiveConduit: In-memory inverted search engine enabling 'One Search Back' capability.

[POS]
Package entry point for expanded dialogue handoffs with dynamic searchable archive channels.
"""

from .expanded_handoff_suite import (
    ExpandedHandoffSuite,
    FullDialogue1200WordAnchorWithSearchableArchiveHandoffSuite,
)
from .expanded_skeleton_anchor_builder import ExpandedSkeletonAnchorBuilder
from .handoff_types import (
    ArchiveSearchResult,
    ExpandedHandoffAnchor,
    ExpandedHandoffConfig,
    HistoricalSessionTurn,
)
from .searchable_old_session_archive_conduit import SearchableOldSessionArchiveConduit

__all__ = [
    "ArchiveSearchResult",
    "ExpandedHandoffAnchor",
    "ExpandedHandoffConfig",
    "ExpandedHandoffSuite",
    "ExpandedSkeletonAnchorBuilder",
    "FullDialogue1200WordAnchorWithSearchableArchiveHandoffSuite",
    "HistoricalSessionTurn",
    "SearchableOldSessionArchiveConduit",
]
