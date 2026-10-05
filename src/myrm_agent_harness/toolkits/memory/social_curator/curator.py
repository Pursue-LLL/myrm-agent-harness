"""High-signal social feed curator engine.

Processes batch social posts against user affinity profile,
eliminates promotional and low-signal noise, and distills Top-10 golden insights.
"""

from collections.abc import Sequence
from datetime import UTC, datetime

from .models import (
    HighSignalBriefing,
    RawSocialPost,
    ScoredSocialInsight,
    UserAffinityProfile,
)
from .scorer import InformationGainScorer


class HighSignalSocialFeedCurator:
    """Orchestrates ingestion, scoring, and curation of social intelligence streams."""

    def __init__(self, min_signal_threshold: float = 0.50) -> None:
        """Initialize curator with customizable minimum signal cutoff."""
        self._min_signal_threshold = max(0.0, min(1.0, min_signal_threshold))

    @property
    def min_signal_threshold(self) -> float:
        """Return the minimum signal score threshold."""
        return self._min_signal_threshold

    def curate_feed(
        self,
        posts: Sequence[RawSocialPost],
        profile: UserAffinityProfile,
        top_n: int = 10,
    ) -> HighSignalBriefing:
        """Filter noise and curate the top N high-signal social insights."""
        total_scanned = len(posts)
        if total_scanned == 0:
            return HighSignalBriefing(
                user_id=profile.user_id,
                generated_at=datetime.now(UTC).isoformat(),
                total_scanned=0,
                noise_filtered_count=0,
                noise_reduction_ratio=0.0,
                top_insights=[],
            )

        scored_insights: list[ScoredSocialInsight] = []
        noise_filtered_count = 0

        for post in posts:
            insight = InformationGainScorer.evaluate(post, profile)
            if insight.is_noise or insight.composite_signal_score < self._min_signal_threshold:
                noise_filtered_count += 1
            else:
                scored_insights.append(insight)

        # Sort descending by composite signal score
        scored_insights.sort(key=lambda item: item.composite_signal_score, reverse=True)
        top_insights = scored_insights[: max(1, top_n)]

        noise_ratio = round(noise_filtered_count / total_scanned, 4)

        return HighSignalBriefing(
            user_id=profile.user_id,
            generated_at=datetime.now(UTC).isoformat(),
            total_scanned=total_scanned,
            noise_filtered_count=noise_filtered_count,
            noise_reduction_ratio=noise_ratio,
            top_insights=top_insights,
        )

    def filter_noise_only(
        self,
        posts: Sequence[RawSocialPost],
        profile: UserAffinityProfile,
    ) -> list[RawSocialPost]:
        """Fast filter returning only raw posts that pass signal criteria."""
        accepted_posts: list[RawSocialPost] = []
        for post in posts:
            insight = InformationGainScorer.evaluate(post, profile)
            if not insight.is_noise and insight.composite_signal_score >= self._min_signal_threshold:
                accepted_posts.append(post)
        return accepted_posts

    def format_briefing_card(self, briefing: HighSignalBriefing) -> str:
        """Format the curated briefing into structured textual card output."""
        lines: list[str] = [
            f"=== High-Signal Social Briefing for {briefing.user_id} ===",
            f"Scanned: {briefing.total_scanned} posts | Noise Blocked: {briefing.noise_filtered_count} ({briefing.noise_reduction_ratio * 100:.1f}%)",
            f"Top Insights Extracted: {len(briefing.top_insights)}",
            "--------------------------------------------------",
        ]

        for idx, insight in enumerate(briefing.top_insights, start=1):
            post = insight.post
            lines.append(
                f"[{idx}] {post.author_handle} ({insight.category.value}) - Signal Score: {insight.composite_signal_score:.2f}"
            )
            lines.append(f"    URL: {post.url}")
            lines.append(f"    Why It Matters: {insight.why_it_matters}")
            if insight.key_takeaways:
                lines.append(f"    Key Takeaway: {insight.key_takeaways[0]}")
            lines.append("")

        return "\n".join(lines)
