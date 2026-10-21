"""Unit tests for utils.prompt_cache_economics."""

import pytest

from myrm_agent_harness.utils.token_economics.cache_economics import (
    coerce_usage_non_negative_int,
    compute_prompt_cache_stats,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, 0),
        (0, 0),
        (42, 42),
        (-1, 0),
        (3.7, 3),
        (float("nan"), 0),
        (float("inf"), 0),
        (float("-inf"), 0),
    ],
)
def test_coerce_usage_non_negative_int(raw: object, expected: int) -> None:
    assert coerce_usage_non_negative_int(raw) == expected


def test_coerce_usage_non_negative_int_invalid_types() -> None:
    """Invalid types (str, bool, etc.) raise TypeError."""
    with pytest.raises(TypeError, match="Expected int \\| float \\| None"):
        coerce_usage_non_negative_int("100")
    with pytest.raises(TypeError, match="Expected int \\| float \\| None"):
        coerce_usage_non_negative_int(True)


def test_compute_prompt_cache_stats_zero_prompt() -> None:
    out = compute_prompt_cache_stats(0, 100)
    assert out == {
        "cache_hit_rate": 0.0,
        "cost_savings_pct": 0.0,
        "cost_savings_absolute": 0.0,
    }


def test_compute_prompt_cache_stats_no_cache_hits() -> None:
    out = compute_prompt_cache_stats(1000, 0)
    assert out["cache_hit_rate"] == 0.0
    assert out["cost_savings_pct"] == pytest.approx(0.0)
    assert out["cost_savings_absolute"] == pytest.approx(0.0)


def test_compute_prompt_cache_stats_partial_hit_matches_logger_formula() -> None:
    """10000 prompt, 8530 cached, default cache_read_ratio=0.1."""
    out = compute_prompt_cache_stats(10000, 8530)
    assert out["cache_hit_rate"] == pytest.approx(0.853)
    # actual_cost = 8530*0.1 + 1470*1.0 = 853 + 1470 = 2323
    # savings_abs = 10000 - 2323 = 7677, savings_pct = 0.7677
    assert out["cost_savings_pct"] == pytest.approx(0.7677, rel=1e-9)
    assert out["cost_savings_absolute"] == pytest.approx(7677.0, rel=1e-9)


def test_compute_prompt_cache_stats_clamp_hit_rate_with_warning(caplog) -> None:
    """Hit rate >1.0 automatically clamped to 1.0 with warning log."""
    with caplog.at_level("WARNING"):
        out = compute_prompt_cache_stats(1000, 1200)
        assert out["cache_hit_rate"] == 1.0
        assert "Cache hit rate exceeds 1.0" in caplog.text
        assert "cached_tokens=1200 > prompt_tokens=1000" in caplog.text


def test_compute_prompt_cache_stats_default_ratio() -> None:
    """Default cache_read_ratio=0.1 (Anthropic 90% off)."""
    out = compute_prompt_cache_stats(10000, 5000)
    # actual_cost = 5000*0.1 + 5000*1.0 = 5500, savings = 4500/10000 = 0.45
    assert out["cache_hit_rate"] == pytest.approx(0.5)
    assert out["cost_savings_pct"] == pytest.approx(0.45, rel=1e-9)


def test_compute_prompt_cache_stats_custom_ratio() -> None:
    """Custom cache_read_ratio=0.5 (OpenAI 50% off)."""
    out = compute_prompt_cache_stats(10000, 5000, cache_read_ratio=0.5)
    # actual_cost = 5000*0.5 + 5000*1.0 = 7500, savings = 2500/10000 = 0.25
    assert out["cache_hit_rate"] == pytest.approx(0.5)
    assert out["cost_savings_pct"] == pytest.approx(0.25, rel=1e-9)
