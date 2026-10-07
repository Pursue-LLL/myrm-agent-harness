"""Package facade for tagging.

[INPUT]
- agent.context_management.tagging.session_tag_filter_engine::SessionTagFilterEngine (POS: Manages tag
  catalog, session associations, queries, and auto-classification.)
- agent.context_management.tagging.session_tag_types::AutoTagSuggestion, SessionFilterQuery, SessionTag,
  TagCategory, TagColor, TagDistribution, TaggedSessionItem, TagMatchMode (POS: Types and models for session
  tag.)

[OUTPUT]
- Re-exports: AutoTagSuggestion, SessionFilterQuery, SessionTag, SessionTagFilterEngine, TagCategory,
  TagColor, TagDistribution, TaggedSessionItem, TagMatchMode

[POS]
Package facade for tagging.
"""

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
