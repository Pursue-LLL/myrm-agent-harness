"""HighSignalSocialFeedCurator package.

Provides high-signal social feed curation, negative spam rejection,
and persona-driven intelligence extraction.
"""

from .curator import HighSignalSocialFeedCurator
from .models import (
    HighSignalBriefing,
    RawSocialPost,
    ScoredSocialInsight,
    SocialInsightCategory,
    UserAffinityProfile,
)
from .persona import UserAffinityProfileBuilder
from .scorer import InformationGainScorer

__all__ = [
    "HighSignalBriefing",
    "HighSignalSocialFeedCurator",
    "InformationGainScorer",
    "RawSocialPost",
    "ScoredSocialInsight",
    "SocialInsightCategory",
    "UserAffinityProfile",
    "UserAffinityProfileBuilder",
]
