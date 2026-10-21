"""Unit tests for ChannelPruner and explicit-scope invariance.

Validates:
1. High-confidence pruning when memory_types_unspecified=True.
2. Invariance protection: caller-specified memory_types are NEVER pruned.
3. Fallback when confidence is below pruning threshold.
4. Pass-through when intent recognition is disabled.
"""

from dataclasses import replace

from myrm_agent_harness.toolkits.memory._internal.channel_pruning import ChannelPruner
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.types import MemoryType


def test_high_confidence_channel_pruning_on_default_query() -> None:
    config = MemoryConfig(embedding_model="test-model")
    all_types = [
        MemoryType.PROFILE,
        MemoryType.SEMANTIC,
        MemoryType.EPISODIC,
        MemoryType.CONVERSATION,
        MemoryType.PROCEDURAL,
    ]
    query = "打包又报错了，提示 cannot find module core_ip_manifest，该怎么修复？"

    result = ChannelPruner.resolve_channels(
        config,
        query,
        all_types,
        memory_types_unspecified=True,
    )

    # ACTION_GUIDANCE high confidence -> pruned to PROCEDURAL and SEMANTIC
    assert MemoryType.PROCEDURAL in result.search_types
    assert MemoryType.SEMANTIC in result.search_types
    assert MemoryType.CONVERSATION not in result.search_types
    assert MemoryType.PROFILE not in result.search_types
    assert MemoryType.EPISODIC not in result.search_types
    assert len(result.pruned_types) == 3
    assert result.decision is not None
    assert result.decision.routing_mode == "pruned"


def test_explicit_scope_invariance_protection() -> None:
    """When caller explicitly specifies memory_types, pruning MUST NOT discard requested types."""
    config = MemoryConfig(embedding_model="test-model")
    # Caller explicitly asked for CONVERSATION and PROFILE, even though query is about error
    requested_types = [MemoryType.CONVERSATION, MemoryType.PROFILE]
    query = "打包又报错了，提示 cannot find module core_ip_manifest"

    result = ChannelPruner.resolve_channels(
        config,
        query,
        requested_types,
        memory_types_unspecified=False,  # Explicitly specified!
    )

    # Invariance guarantees all requested channels survive
    assert result.search_types == requested_types
    assert len(result.pruned_types) == 0
    # But type weights can still be dynamically adapted
    assert result.decision is not None


def test_moderate_confidence_adaptive_weighting_without_pruning() -> None:
    config = MemoryConfig(embedding_model="test-model")
    all_types = [
        MemoryType.PROFILE,
        MemoryType.SEMANTIC,
        MemoryType.EPISODIC,
        MemoryType.CONVERSATION,
        MemoryType.PROCEDURAL,
    ]
    # Broad query without strong triggering keywords
    query = "聊聊上次的会谈，或者随便谈谈"

    result = ChannelPruner.resolve_channels(
        config,
        query,
        all_types,
        memory_types_unspecified=True,
    )

    # Should not prune when confidence is not >= 0.85
    assert len(result.pruned_types) == 0
    assert len(result.search_types) == 5


def test_disabled_intent_recognition() -> None:
    base_config = MemoryConfig(embedding_model="test-model")
    disabled_config = replace(
        base_config,
        retrieval=replace(base_config.retrieval, enable_intent_recognition=False),
    )
    all_types = [MemoryType.PROFILE, MemoryType.SEMANTIC, MemoryType.EPISODIC]
    query = "报错异常"

    result = ChannelPruner.resolve_channels(
        disabled_config,
        query,
        all_types,
        memory_types_unspecified=True,
    )

    assert result.search_types == all_types
    assert result.decision is None
    assert len(result.pruned_types) == 0
