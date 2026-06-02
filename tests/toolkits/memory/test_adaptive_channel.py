"""Tests for adaptive dual-channel selection logic."""

from myrm_agent_harness.toolkits.memory.adaptive import should_use_dual_channel
from myrm_agent_harness.toolkits.memory.config import RetrievalConfig


def test_short_query_uses_single_channel() -> None:
    """Short queries without special features should use summary only."""
    config = RetrievalConfig()
    assert not should_use_dual_channel("Python", config)
    assert not should_use_dual_channel("bug", config)
    assert not should_use_dual_channel("last time", config)


def test_long_query_uses_dual_channel() -> None:
    """Long queries exceeding threshold should use dual channel."""
    config = RetrievalConfig(adaptive_threshold=5)
    long_query = "How to optimize Python async performance"
    assert should_use_dual_channel(long_query, config)


def test_quoted_phrase_forces_dual_channel() -> None:
    """Queries with quotes need exact matching from raw verbatim."""
    config = RetrievalConfig()
    assert should_use_dual_channel('"bug"', config)
    assert should_use_dual_channel("find 'performance'", config)
    assert should_use_dual_channel('search for "memory leak"', config)


def test_high_diversity_triggers_dual_channel() -> None:
    """High word diversity indicates semantic complexity."""
    config = RetrievalConfig(adaptive_diversity_threshold=0.7)

    # Low diversity (repeated words)
    low_diversity = "Python Python tutorial"  # 2/3 = 0.67
    assert not should_use_dual_channel(low_diversity, config)

    # High diversity (all unique)
    high_diversity = "async await performance"  # 3/3 = 1.0
    assert should_use_dual_channel(high_diversity, config)


def test_diversity_requires_minimum_length() -> None:
    """Diversity check only applies to queries with >=3 tokens."""
    config = RetrievalConfig(adaptive_diversity_threshold=0.7)

    # 2 tokens, high diversity but too short
    assert not should_use_dual_channel("async await", config)

    # 3 tokens, high diversity
    assert should_use_dual_channel("async await performance", config)


def test_custom_threshold() -> None:
    """Config allows customizing token threshold."""
    config_low = RetrievalConfig(adaptive_threshold=3)
    config_high = RetrievalConfig(adaptive_threshold=10)

    query = "Python Python bug"  # 3 tokens, 67% diversity
    assert should_use_dual_channel(query, config_low)
    # High threshold and low diversity prevents dual
    assert not should_use_dual_channel(query, config_high)


def test_custom_diversity_threshold() -> None:
    """Config allows customizing diversity threshold."""
    config_strict = RetrievalConfig(adaptive_diversity_threshold=0.9)
    config_loose = RetrievalConfig(adaptive_diversity_threshold=0.5)

    query = "Python async tutorial tutorial"  # 3/4 = 0.75
    assert not should_use_dual_channel(query, config_strict)
    assert should_use_dual_channel(query, config_loose)


def test_combined_factors() -> None:
    """Test realistic scenarios with multiple factors."""
    config = RetrievalConfig()

    # Short + no quotes + low diversity → summary only
    assert not should_use_dual_channel("bug fix", config)

    # Short + quotes → dual
    assert should_use_dual_channel('"bug"', config)

    # Long → dual
    assert should_use_dual_channel("How to fix memory leak", config)

    # Short + high diversity → dual
    assert should_use_dual_channel("async await error", config)


def test_edge_cases() -> None:
    """Test edge cases and boundary conditions."""
    config = RetrievalConfig(adaptive_threshold=5)

    # Empty query
    assert not should_use_dual_channel("", config)

    # Single space
    assert not should_use_dual_channel(" ", config)

    # Exactly at threshold
    query_5_tokens = "one one one one one"  # Low diversity to isolate token threshold
    assert should_use_dual_channel(query_5_tokens, config)

    # Just below threshold
    query_4_tokens = "one one one one"  # Low diversity
    assert not should_use_dual_channel(query_4_tokens, config)


def test_real_world_queries() -> None:
    """Test with realistic user queries."""
    config = RetrievalConfig()

    # Simple keyword searches → summary
    assert not should_use_dual_channel("error", config)
    assert not should_use_dual_channel("API", config)

    # Code snippet searches → dual
    assert should_use_dual_channel('find "async def"', config)

    # Complex questions → dual
    assert should_use_dual_channel("How do I optimize database queries?", config)

    # Person name searches → depends on length
    assert not should_use_dual_channel("张三", config)  # 1 token in Chinese
    assert should_use_dual_channel("What did 张三 say?", config)  # Long enough


def test_custom_strategy_override() -> None:
    """Business layer can override with custom adaptive strategy."""

    class AlwaysDualStrategy:
        """Custom strategy that always uses dual channel."""

        def should_use_dual_channel(self, query: str) -> bool:
            return True

    config = RetrievalConfig(adaptive_strategy=AlwaysDualStrategy())

    # Even short queries use dual when strategy overrides
    assert should_use_dual_channel("bug", config)
    assert should_use_dual_channel("x", config)


def test_strategy_override_precedence() -> None:
    """Custom strategy takes precedence over default logic."""

    class NeverDualStrategy:
        """Custom strategy that never uses dual channel."""

        def should_use_dual_channel(self, query: str) -> bool:
            return False

    config = RetrievalConfig(adaptive_strategy=NeverDualStrategy())

    # Even long queries with quotes use summary when strategy overrides
    assert not should_use_dual_channel('"exact phrase match"', config)
    assert not should_use_dual_channel("How to optimize Python async performance", config)
