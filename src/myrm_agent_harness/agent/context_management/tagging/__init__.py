# ============================================================================
# Session Hierarchical Tagging & Metadata Filter Subpackage (Item 156)
# ============================================================================

from .session_tag_filter_engine import SessionTagFilterEngine
from .session_tag_types import (
    AutoTagSuggestion,
    SessionFilterQuery,
    SessionTag,
    TagCategory,
    TagColor,
    TagDistribution,
    TaggedSessionItem,
    TagMatchMode,
)

__all__ = [
    "AutoTagSuggestion",
    "SessionFilterQuery",
    "SessionTag",
    "SessionTagFilterEngine",
    "TagCategory",
    "TagColor",
    "TagDistribution",
    "TaggedSessionItem",
    "TagMatchMode",
]
