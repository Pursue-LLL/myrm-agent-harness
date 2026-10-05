"""Comprehensive unit tests for HighSignalSocialFeedCurator."""

from myrm_agent_harness.toolkits.memory.social_curator import (
    HighSignalSocialFeedCurator,
    InformationGainScorer,
    RawSocialPost,
    SocialInsightCategory,
    UserAffinityProfileBuilder,
)


def test_user_affinity_profile_builder_basic() -> None:
    """Test manual and memory dictionary extraction with deduplication."""
    profile = UserAffinityProfileBuilder.build_from_attributes(
        user_id="user_architect_1",
        core_identity="Senior Autonomous Agent Architect",
        active_projects=["Myrm Agent", "myrm agent", "Sandbox Runtime"],
        tech_stack=["Python", "Rust", "Qdrant", "SQLite", "python"],
        key_interests=["Memory Evolution", "Execution Sandbox"],
        negative_filters=["airdrop", "airdrop", "crypto pump"],
        known_knowledge_signatures={"simple rag", "basic prompt"},
    )

    assert profile.user_id == "user_architect_1"
    assert profile.core_identity == "Senior Autonomous Agent Architect"
    assert profile.active_projects == ["Myrm Agent", "Sandbox Runtime"]
    assert profile.tech_stack == ["Python", "Rust", "Qdrant", "SQLite"]
    assert profile.negative_filters == ["airdrop", "crypto pump"]
    assert "simple rag" in profile.known_knowledge_signatures

    # Test build from memory dict
    mem_dict = {
        "identity": "Principal System Engineer",
        "projects": ["Distributed Vector Engine"],
        "tech_stack": ["Rust", "Tokio"],
        "topics": ["High Throughput Indexing"],
        "known_facts": ["btree index baseline"],
    }
    extracted_profile = UserAffinityProfileBuilder.build_from_memory_dict(
        user_id="user_mem_2",
        memory_payload=mem_dict,
    )
    assert extracted_profile.core_identity == "Principal System Engineer"
    assert "Rust" in extracted_profile.tech_stack
    assert "btree index baseline" in extracted_profile.known_knowledge_signatures


def test_scorer_negative_filter_hard_rejection() -> None:
    """Test spam and marketing posts are hard-filtered with zero score."""
    profile = UserAffinityProfileBuilder.build_from_attributes(
        user_id="user_test",
        core_identity="Lead Architect",
        negative_filters=["airdrop", "giveaway", "retweet to win"],
    )

    spam_post = RawSocialPost(
        post_id="p_spam_1",
        author_handle="@crypto_shill",
        content="Massive airdrop live now! Retweet to win $1000 in tokens!",
        published_at="2026-10-05T12:00:00Z",
        url="https://x.com/crypto_shill/status/1",
        likes=5000,
        reposts=2000,
    )

    insight = InformationGainScorer.evaluate(spam_post, profile)
    assert insight.is_noise is True
    assert insight.category == SocialInsightCategory.NOISE_DISMISSED
    assert insight.composite_signal_score == 0.0
    assert insight.rejection_reason is not None
    assert "airdrop" in insight.rejection_reason


def test_scorer_substance_and_affinity_scoring() -> None:
    """Test deep technical substance and venture matching yields high composite score."""
    profile = UserAffinityProfileBuilder.build_from_attributes(
        user_id="user_test",
        core_identity="Agent Framework Creator",
        active_projects=["Myrm Agent"],
        tech_stack=["Python", "Qdrant", "SQLite"],
        key_interests=["Execution Sandbox", "Memory Evolution"],
        known_knowledge_signatures={"basic vector db"},
    )

    hardcore_post = RawSocialPost(
        post_id="p_tech_1",
        author_handle="@frontier_researcher",
        content=(
            "Released v2.0 of our micro-VM sandbox architecture for Myrm Agent ecosystem.\n"
            "Benchmarks show 99.8% memory reduction and 18 tok/s sustained throughput on Qdrant HNSW indexing.\n"
            "Full open source implementation on GitHub."
        ),
        published_at="2026-10-05T14:30:00Z",
        url="https://x.com/frontier_researcher/status/2",
        likes=1200,
        bookmarks=350,
        has_code_or_media=True,
    )

    insight = InformationGainScorer.evaluate(hardcore_post, profile)
    assert insight.is_noise is False
    assert insight.affinity_score > 0.60
    assert insight.substance_score > 0.70
    assert insight.novelty_score >= 0.75
    assert insight.composite_signal_score > 0.70
    assert insight.category in (
        SocialInsightCategory.ACTIONABLE_ENGINEERING,
        SocialInsightCategory.BREAKTHROUGH_TECH,
        SocialInsightCategory.COMPETITOR_BENCHMARK,
    )
    assert len(insight.key_takeaways) > 0


def test_curator_end_to_end_feed_filtering_and_ranking() -> None:
    """Test curation pipeline filters noise, computes reduction ratio, and extracts top insights."""
    profile = UserAffinityProfileBuilder.build_from_attributes(
        user_id="yulu_founder",
        core_identity="AI Autonomous Agent Architect",
        active_projects=["Myrm Agent"],
        tech_stack=["Python", "Rust", "Qdrant"],
        key_interests=["Sandbox Runtime", "Memory Evolution"],
        negative_filters=["airdrop", "giveaway", "retweet to win", "discord invite"],
    )

    posts = [
        # Spam 1
        RawSocialPost(
            post_id="post_spam_1",
            author_handle="@crypto_bot",
            content="Join discord invite to claim free airdrop token!",
            published_at="2026-10-05T01:00:00Z",
            url="https://x.com/post_spam_1",
        ),
        # Low-signal noise 2
        RawSocialPost(
            post_id="post_noise_2",
            author_handle="@chatty",
            content="Good morning everyone! Have a nice coffee today.",
            published_at="2026-10-05T02:00:00Z",
            url="https://x.com/post_noise_2",
        ),
        # High-signal Post 1 (Benchmark)
        RawSocialPost(
            post_id="post_high_1",
            author_handle="@benchmark_lab",
            content="Deep comparison benchmark: Myrm Agent runtime vs competitor frameworks. Latency 2.1ms with SQLite daemon.",
            published_at="2026-10-05T03:00:00Z",
            url="https://x.com/post_high_1",
            likes=800,
            bookmarks=210,
            has_code_or_media=True,
        ),
        # High-signal Post 2 (Breakthrough)
        RawSocialPost(
            post_id="post_high_2",
            author_handle="@ai_scientist",
            content="Novel architecture paper release: Zero-overhead memory evolution protocol with 99.5% accuracy.",
            published_at="2026-10-05T04:00:00Z",
            url="https://x.com/post_high_2",
            likes=1500,
            bookmarks=400,
            has_code_or_media=True,
        ),
        # High-signal Post 3 (Engineering)
        RawSocialPost(
            post_id="post_high_3",
            author_handle="@systems_eng",
            content="GitHub repo release for Rust container sandbox manager with Qdrant vector backend integration.",
            published_at="2026-10-05T05:00:00Z",
            url="https://x.com/post_high_3",
            likes=600,
            bookmarks=150,
            has_code_or_media=True,
        ),
    ]

    curator = HighSignalSocialFeedCurator(min_signal_threshold=0.45)
    briefing = curator.curate_feed(posts, profile, top_n=2)

    assert briefing.total_scanned == 5
    assert briefing.noise_filtered_count >= 2
    assert briefing.noise_reduction_ratio >= 0.40
    assert len(briefing.top_insights) == 2

    # First insight should have highest score
    assert briefing.top_insights[0].composite_signal_score >= briefing.top_insights[1].composite_signal_score

    # Test briefing card formatting
    card_text = curator.format_briefing_card(briefing)
    assert "High-Signal Social Briefing for yulu_founder" in card_text
    assert "Top Insights Extracted: 2" in card_text

    # Test fast noise filtering helper
    accepted = curator.filter_noise_only(posts, profile)
    assert len(accepted) == 3
    assert all(p.post_id not in ("post_spam_1", "post_noise_2") for p in accepted)

    # Test empty feed edge case
    empty_briefing = curator.curate_feed([], profile)
    assert empty_briefing.total_scanned == 0
    assert empty_briefing.noise_filtered_count == 0
    assert len(empty_briefing.top_insights) == 0
