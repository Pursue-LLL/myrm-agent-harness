"""HighSignalSocialFeedCurator package.

Provides high-signal social feed curation, negative spam rejection,
and persona-driven intelligence extraction.

[INPUT]
- toolkits.memory.social_curator.curator::HighSignalSocialFeedCurator (POS: High-signal social feed curator
  engine.)
- toolkits.memory.social_curator.models::HighSignalBriefing, RawSocialPost, ScoredSocialInsight,
  SocialInsightCategory, UserAffinityProfile (POS: Data models for HighSignalSocialFeedCurator.)
- toolkits.memory.social_curator.persona::UserAffinityProfileBuilder (POS: Persona and venture affinity
  profile builder.)
- toolkits.memory.social_curator.scorer::InformationGainScorer (POS: Information gain and aha-moment scoring
  operator for social feed items.)

[OUTPUT]
- Package facade re-exporting 8 public names: HighSignalBriefing, HighSignalSocialFeedCurator,
  InformationGainScorer, RawSocialPost, ScoredSocialInsight, SocialInsightCategory, UserAffinityProfile,
  UserAffinityProfileBuilder

[POS]
HighSignalSocialFeedCurator package.
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
