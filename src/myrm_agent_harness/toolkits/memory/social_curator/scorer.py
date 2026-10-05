"""Information gain and aha-moment scoring operator for social feed items.

Evaluates negative spam filtering, domain affinity, engineering substance,
and knowledge novelty to calculate an objective composite signal score.
"""

import re

from .models import (
    RawSocialPost,
    ScoredSocialInsight,
    SocialInsightCategory,
    UserAffinityProfile,
)


class InformationGainScorer:
    """Multi-dimensional information gain and technical substance evaluation operator."""

    @classmethod
    def evaluate(
        cls,
        post: RawSocialPost,
        profile: UserAffinityProfile,
    ) -> ScoredSocialInsight:
        """Evaluate a raw social media post against user affinity profile."""
        lower_content = post.content.lower()

        # Step 1: Negative Hard Filter Gate
        rejection_reason = cls._check_negative_filter(lower_content, profile.negative_filters)
        if rejection_reason is not None:
            return ScoredSocialInsight(
                post=post,
                category=SocialInsightCategory.NOISE_DISMISSED,
                affinity_score=0.0,
                substance_score=0.0,
                novelty_score=0.0,
                composite_signal_score=0.0,
                why_it_matters="Filtered as promotional spam or noise.",
                key_takeaways=[],
                is_noise=True,
                rejection_reason=rejection_reason,
            )

        # Step 2: Affinity Score Calculation (0.0 ~ 1.0)
        affinity_score, matched_interests = cls._calculate_affinity(
            lower_content, profile
        )

        # Step 3: Substance Score Calculation (0.0 ~ 1.0)
        substance_score, key_substance_markers = cls._calculate_substance(
            post, lower_content
        )

        # Step 4: Novelty Score Calculation (0.0 ~ 1.0)
        novelty_score = cls._calculate_novelty(
            lower_content, profile.known_knowledge_signatures
        )

        # Step 5: Composite Weighted Signal Score
        composite_score = round(
            0.40 * affinity_score + 0.35 * substance_score + 0.25 * novelty_score,
            4,
        )

        # Determine semantic category
        category = cls._determine_category(
            lower_content, substance_score, novelty_score
        )

        # Derive why it matters and actionable takeaways
        why_it_matters = cls._generate_why_it_matters(
            profile, matched_interests, substance_score, category
        )
        key_takeaways = cls._extract_takeaways(
            post.content, key_substance_markers
        )

        return ScoredSocialInsight(
            post=post,
            category=category,
            affinity_score=affinity_score,
            substance_score=substance_score,
            novelty_score=novelty_score,
            composite_signal_score=composite_score,
            why_it_matters=why_it_matters,
            key_takeaways=key_takeaways,
            is_noise=False,
            rejection_reason=None,
        )

    @staticmethod
    def _check_negative_filter(
        content: str,
        negative_filters: list[str],
    ) -> str | None:
        """Return rejection reason if negative spam keywords are detected."""
        for pattern in negative_filters:
            normalized_pat = pattern.strip().lower()
            if normalized_pat and normalized_pat in content:
                return f"Contains prohibited spam/marketing keyword: '{normalized_pat}'"
        return None

    @staticmethod
    def _calculate_affinity(
        content: str,
        profile: UserAffinityProfile,
    ) -> tuple[float, list[str]]:
        """Calculate alignment with active ventures, tech stack, and key interests."""
        matched: list[str] = []
        score = 0.15  # baseline curiosity score

        # Check active ventures (high weight +0.30 per match, capped at 0.50)
        venture_hits = 0
        for project in profile.active_projects:
            if project.lower() in content:
                venture_hits += 1
                matched.append(f"Venture: {project}")
        score += min(venture_hits * 0.30, 0.50)

        # Check tech stack (+0.12 per match, capped at 0.36)
        tech_hits = 0
        for tech in profile.tech_stack:
            if tech.lower() in content:
                tech_hits += 1
                matched.append(f"Stack: {tech}")
        score += min(tech_hits * 0.12, 0.36)

        # Check core interests (+0.15 for exact phrase, +0.10 for key term, capped at 0.30)
        interest_hits = 0.0
        for interest in profile.key_interests:
            lower_interest = interest.lower()
            if lower_interest in content:
                interest_hits += 1.0
                matched.append(f"Interest: {interest}")
            else:
                tokens = [t.strip() for t in lower_interest.split() if len(t.strip()) >= 4]
                hit_token = next((t for t in tokens if t in content), None)
                if hit_token:
                    interest_hits += 0.67
                    matched.append(f"Interest: {interest} ({hit_token})")
        score += min(interest_hits * 0.15, 0.30)

        return min(round(score, 4), 1.0), matched

    @staticmethod
    def _calculate_substance(
        post: RawSocialPost,
        content: str,
    ) -> tuple[float, list[str]]:
        """Evaluate technical depth, benchmarking, and empirical code evidence."""
        score = 0.20
        markers: list[str] = []

        # Quantitative benchmarks (e.g. "99.8%", "18 tok/s", "1024-dim", "2.1ms")
        has_quant_metrics = bool(re.search(r"\b\d+(\.\d+)?(%|ms|s|x|gb|mb|k|m|tokens?|dim)\b", content))
        if has_quant_metrics:
            score += 0.25
            markers.append("Quantitative benchmark metrics")

        # Concrete architectural / systems terminology
        architecture_patterns = [
            "sandbox", "container", "runtime", "sqlite", "qdrant", "hnsw",
            "vector", "embedding", "git", "submodule", "pipeline", "compiler",
            "protocol", "distributed", "daemon", "caching", "kernel",
        ]
        arch_hits = sum(1 for pat in architecture_patterns if pat in content)
        if arch_hits > 0:
            score += min(arch_hits * 0.10, 0.30)
            markers.append(f"Systems architecture depth ({arch_hits} keywords)")

        # Media or code attachment
        if post.has_code_or_media:
            score += 0.15
            markers.append("Embedded technical artifact or media")

        # Bookmark-to-like engagement ratio (high bookmark signifies high-utility reference value)
        if post.bookmarks > 0 and post.likes > 0:
            bookmark_ratio = post.bookmarks / post.likes
            if bookmark_ratio >= 0.10:
                score += 0.15
                markers.append("Exceptional bookmark-to-like utility ratio (>10%)")

        return min(round(score, 4), 1.0), markers

    @staticmethod
    def _calculate_novelty(
        content: str,
        known_signatures: frozenset[str],
    ) -> float:
        """Penalize trivial already-established knowledge and reward breakthroughs."""
        # Check overlap with existing knowledge
        overlap_count = sum(1 for sig in known_signatures if sig in content)
        if overlap_count >= 2:
            # High overlap with known facts -> lower novelty
            return 0.35

        # Check breakthrough buzzwords
        breakthrough_terms = [
            "breakthrough", "state of the art", "sota", "first time",
            "novel architecture", "paradigm shift", "open source release",
            "paper release", "v2.0", "zero-overhead",
        ]
        breakthrough_hits = sum(1 for term in breakthrough_terms if term in content)
        if breakthrough_hits > 0:
            return min(0.70 + breakthrough_hits * 0.15, 1.0)

        return 0.75  # Default novelty for unclassified new post

    @staticmethod
    def _determine_category(
        content: str,
        substance_score: float,
        novelty_score: float,
    ) -> SocialInsightCategory:
        """Derive the insight category based on semantic flags and scores."""
        if any(term in content for term in ["benchmark", "comparison", "vs", "competitor", "faster than"]):
            return SocialInsightCategory.COMPETITOR_BENCHMARK
        if substance_score >= 0.70 and any(term in content for term in ["github", "release", "implementation", "repo", "guide"]):
            return SocialInsightCategory.ACTIONABLE_ENGINEERING
        if novelty_score >= 0.80 and any(term in content for term in ["paper", "breakthrough", "architecture", "frontier"]):
            return SocialInsightCategory.BREAKTHROUGH_TECH
        return SocialInsightCategory.MARKET_TREND

    @staticmethod
    def _generate_why_it_matters(
        profile: UserAffinityProfile,
        matched_interests: list[str],
        substance_score: float,
        category: SocialInsightCategory,
    ) -> str:
        """Generate tailored explanation for why this post deserves user attention."""
        context_str = ", ".join(matched_interests[:2]) if matched_interests else "AI Agent engineering"
        substance_desc = "deep empirical metrics" if substance_score >= 0.70 else "relevant industry shifts"

        return (
            f"Directly relevant to {profile.core_identity} through {context_str}. "
            f"Provides actionable intelligence on {category.value} with {substance_desc}."
        )

    @staticmethod
    def _extract_takeaways(
        content: str,
        markers: list[str],
    ) -> list[str]:
        """Extract key bullet points from post content."""
        takeaways: list[str] = []
        sentences = [s.strip() for s in content.split("\n") if s.strip()]
        for line in sentences:
            if any(char in line for char in [":", "-", "•", ">"]) or len(line) > 20:
                takeaways.append(line[:120])
            if len(takeaways) >= 3:
                break
        if not takeaways:
            takeaways.append(content[:140])
        return takeaways
