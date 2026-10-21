"""Tests for ExplicitCacheProcessor parameter validation.

Ensures constructor parameter validation catches invalid configurations
and enforces Anthropic API constraints (20-block lookback window, 4 max breakpoints).
"""

import pytest

from myrm_agent_harness.agent.context_management.pipeline.processors.cache_optimizer import ExplicitCacheProcessor


def test_invalid_safe_block_interval_zero() -> None:
    """Reject safe_block_interval=0 (violates 1-19 range)."""
    with pytest.raises(ValueError, match="safe_block_interval 必须是 1-19 之间的整数"):
        ExplicitCacheProcessor(safe_block_interval=0)


def test_invalid_safe_block_interval_negative() -> None:
    """Reject negative safe_block_interval."""
    with pytest.raises(ValueError, match="safe_block_interval 必须是 1-19 之间的整数"):
        ExplicitCacheProcessor(safe_block_interval=-5)


def test_invalid_safe_block_interval_too_large() -> None:
    """Reject safe_block_interval=20 (exceeds 20-block lookback window limit)."""
    with pytest.raises(ValueError, match="safe_block_interval 必须是 1-19 之间的整数"):
        ExplicitCacheProcessor(safe_block_interval=20)


def test_invalid_safe_block_interval_not_int() -> None:
    """Reject non-integer safe_block_interval."""
    with pytest.raises(ValueError, match="safe_block_interval 必须是 1-19 之间的整数"):
        ExplicitCacheProcessor(safe_block_interval=15.5)  # type: ignore[arg-type]


def test_invalid_min_message_gap_zero() -> None:
    """Reject min_message_gap=0 (violates 1-10 range)."""
    with pytest.raises(ValueError, match="min_message_gap 必须是 1-10 之间的整数"):
        ExplicitCacheProcessor(min_message_gap=0)


def test_invalid_min_message_gap_negative() -> None:
    """Reject negative min_message_gap."""
    with pytest.raises(ValueError, match="min_message_gap 必须是 1-10 之间的整数"):
        ExplicitCacheProcessor(min_message_gap=-1)


def test_invalid_min_message_gap_too_large() -> None:
    """Reject min_message_gap=11 (exceeds maximum)."""
    with pytest.raises(ValueError, match="min_message_gap 必须是 1-10 之间的整数"):
        ExplicitCacheProcessor(min_message_gap=11)


def test_invalid_max_breakpoints_zero() -> None:
    """Reject max_breakpoints=0 (violates 1-4 Anthropic limit)."""
    with pytest.raises(ValueError, match="max_breakpoints 必须是 1-4 之间的整数"):
        ExplicitCacheProcessor(max_breakpoints=0)


def test_invalid_max_breakpoints_negative() -> None:
    """Reject negative max_breakpoints."""
    with pytest.raises(ValueError, match="max_breakpoints 必须是 1-4 之间的整数"):
        ExplicitCacheProcessor(max_breakpoints=-2)


def test_invalid_max_breakpoints_too_large() -> None:
    """Reject max_breakpoints=5 (exceeds Anthropic 4-breakpoint limit)."""
    with pytest.raises(ValueError, match="max_breakpoints 必须是 1-4 之间的整数"):
        ExplicitCacheProcessor(max_breakpoints=5)


def test_valid_boundary_values() -> None:
    """Accept valid boundary values for all parameters."""
    # Minimum valid values
    processor1 = ExplicitCacheProcessor(safe_block_interval=1, min_message_gap=1, max_breakpoints=1)
    assert processor1 is not None

    # Maximum valid values
    processor2 = ExplicitCacheProcessor(safe_block_interval=19, min_message_gap=10, max_breakpoints=4)
    assert processor2 is not None


def test_valid_default_values() -> None:
    """Default constructor values satisfy constraints."""
    processor = ExplicitCacheProcessor()
    assert processor is not None
