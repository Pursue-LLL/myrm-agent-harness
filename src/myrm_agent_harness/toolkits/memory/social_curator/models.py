"""Data models for HighSignalSocialFeedCurator.

Provides strongly typed domain structures for user affinity profiling,
raw social posts, multi-dimensional scoring, and high-signal briefing delivery.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class SocialInsightCategory(StrEnum):
    """Categorization for high-signal curated social media insights."""

    BREAKTHROUGH_TECH = "breakthrough_tech"
    COMPETITOR_BENCHMARK = "competitor_benchmark"
    ACTIONABLE_ENGINEERING = "actionable_engineering"
    MARKET_TREND = "market_trend"
    NOISE_DISMISSED = "noise_dismissed"


@dataclass(frozen=True)
class UserAffinityProfile:
    """Compact contextual user profile aggregated from long-term memory."""

    user_id: str
    core_identity: str
    active_projects: list[str] = field(default_factory=list)
    tech_stack: list[str] = field(default_factory=list)
    key_interests: list[str] = field(default_factory=list)
    negative_filters: list[str] = field(default_factory=list)
    known_knowledge_signatures: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class RawSocialPost:
    """Unprocessed incoming post from social media platforms (e.g. X/Twitter)."""

    post_id: str
    author_handle: str
    content: str
    published_at: str
    url: str
    likes: int = 0
    reposts: int = 0
    replies: int = 0
    bookmarks: int = 0
    has_code_or_media: bool = False


@dataclass(frozen=True)
class ScoredSocialInsight:
    """Evaluated social insight with multidimensional signal ratings."""

    post: RawSocialPost
    category: SocialInsightCategory
    affinity_score: float
    substance_score: float
    novelty_score: float
    composite_signal_score: float
    why_it_matters: str
    key_takeaways: list[str] = field(default_factory=list)
    is_noise: bool = False
    rejection_reason: str | None = None


@dataclass(frozen=True)
class HighSignalBriefing:
    """Top-tier curated briefing summarizing high-value missed intelligence."""

    user_id: str
    generated_at: str
    total_scanned: int
    noise_filtered_count: int
    noise_reduction_ratio: float
    top_insights: list[ScoredSocialInsight] = field(default_factory=list)
