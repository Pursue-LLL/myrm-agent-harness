"""Contested memories must survive the retention pass until a human settles them."""

from datetime import UTC, datetime, timedelta

from myrm_agent_harness.toolkits.memory.strategies.deduplicator import (
    _CONTESTED_KEY,
    _CONTESTED_VALUE,
    _mark_contested,
)
from myrm_agent_harness.toolkits.memory.strategies.forgetting import (
    ForgettingConfig,
    ForgettingStrategy,
)
from myrm_agent_harness.toolkits.memory.types import SemanticMemory

# Old, unrated and unimportance-scored: the only shape the retention pass can cull,
# since importance and rating each floor the total at the threshold when defaulted.
_OLD = datetime.now(UTC) - timedelta(days=400)


def _aged(content: str) -> SemanticMemory:
    return SemanticMemory(
        content=content,
        confidence=0.35,
        access_count=0,
        created_at=_OLD,
        importance=0.0,
        user_rating=0.0,
    )


def _should_forget(memory: SemanticMemory) -> bool:
    return ForgettingStrategy(ForgettingConfig()).calculate_retention_score(memory).should_forget


def test_mark_contested_sets_the_key_retention_reads() -> None:
    memory = SemanticMemory(content="项目缓存使用 Redis")
    _mark_contested(memory)
    assert memory.metadata[_CONTESTED_KEY] == _CONTESTED_VALUE


def test_contested_memory_is_not_forgotten() -> None:
    """A decayed record of a rejected option must not expire before resolution."""
    contested = _aged("项目缓存使用 Redis")
    _mark_contested(contested)

    assert _should_forget(contested) is False


def test_uncaged_memory_of_the_same_shape_is_forgotten() -> None:
    """The flag is what spares it; without it the same record is culled."""
    plain = _aged("项目缓存使用 Redis")

    assert _should_forget(plain) is True
