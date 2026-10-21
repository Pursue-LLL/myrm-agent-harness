"""真实 litellm 回归测试套件 (零 Mock，彻底验证真实计价与缓存折扣)."""

import litellm
import pytest

from myrm_agent_harness.utils.token_economics.cost_engine import (
    CostResult,
    CostStatus,
    compute_cost_by_tokens,
)


def test_real_litellm_mainstream_model_pricing() -> None:
    """真实验证主流模型 (gpt-4o) 计价成功且大于零."""
    result = compute_cost_by_tokens(
        model="gpt-4o",
        prompt_tokens=1000,
        completion_tokens=200,
    )
    assert result.is_known is True
    assert result.status == CostStatus.ACTUAL
    assert result.usd > 0.0
    # gpt-4o: prompt 1k @ 2.50/M = 0.0025, completion 200 @ 10.00/M = 0.002 -> 0.0045
    assert abs(result.usd - 0.0045) < 1e-5


def test_real_litellm_cache_aware_pricing_discount() -> None:
    """真实验证缓存感知计价：缓存读取命中时费用严格低于无缓存命中."""
    # 场景 A: 无缓存命中 (1000 全部算 prompt)
    res_uncached = compute_cost_by_tokens(
        model="gpt-4o",
        prompt_tokens=1000,
        completion_tokens=200,
        cache_read_tokens=0,
    )

    # 场景 B: 800 tokens 命中缓存 (按缓存折扣价计费)
    res_cached = compute_cost_by_tokens(
        model="gpt-4o",
        prompt_tokens=1000,
        completion_tokens=200,
        cache_read_tokens=800,
    )

    assert res_uncached.is_known is True
    assert res_cached.is_known is True
    assert res_cached.usd < res_uncached.usd
    # gpt-4o 缓存读取减半节省
    assert res_cached.usd == pytest.approx(0.0035, abs=1e-5)


def test_real_litellm_provider_qualified_name() -> None:
    """真实验证供应商限定名 (deepseek/deepseek-chat) 计价成功."""
    result = compute_cost_by_tokens(
        model="deepseek/deepseek-chat",
        prompt_tokens=5000,
        completion_tokens=1000,
    )
    assert result.is_known is True
    assert result.status in (CostStatus.ACTUAL, CostStatus.ESTIMATED)
    assert result.usd > 0.0


def test_real_litellm_custom_registered_pricing_both_keys() -> None:
    """真实验证自定义单价登记后，限定名与裸模型名均可成功计价."""
    test_qualified = "custom_openai/mimo-v2.5-pro-test"
    test_bare = "mimo-v2.5-pro-test"

    custom_entry = {
        "input_cost_per_token": 0.000002,  # $2.00 / 1M
        "output_cost_per_token": 0.000006,  # $6.00 / 1M
        "cache_read_input_token_cost": 0.0000005,  # $0.50 / 1M
        "litellm_provider": "custom_openai",
        "max_tokens": 128000,
    }
    bare_entry = dict(custom_entry)
    bare_entry["litellm_provider"] = "openai"

    litellm.model_cost[test_qualified] = custom_entry
    litellm.model_cost[test_bare] = bare_entry

    # 1. 验证限定名计价
    res_qual = compute_cost_by_tokens(
        model=test_qualified,
        prompt_tokens=1000,
        completion_tokens=500,
        cache_read_tokens=800,
    )
    assert res_qual.is_known is True
    assert res_qual.usd > 0.0
    # prompt 1000 (800 cached @ 0.0000005 = 0.0004, 200 non-cached @ 0.000002 = 0.0004 -> 0.0008)
    # comp 500 @ 0.000006 = 0.003 -> total = 0.0038
    assert res_qual.usd == pytest.approx(0.0038, abs=1e-5)

    # 2. 验证裸模型名计价
    res_bare = compute_cost_by_tokens(
        model=test_bare,
        prompt_tokens=1000,
        completion_tokens=500,
        cache_read_tokens=800,
    )
    assert res_bare.is_known is True
    assert res_bare.usd > 0.0
    assert res_bare.usd == pytest.approx(0.0038, abs=1e-5)


def test_real_litellm_legal_model_must_not_return_unknown() -> None:
    """断言合法主流模型和正常 token 数绝对不能返回 UNKNOWN."""
    result = compute_cost_by_tokens(
        model="gpt-4o-mini",
        prompt_tokens=1000,
        completion_tokens=100,
    )
    assert result.status != CostStatus.UNKNOWN
    assert result.usd > 0.0
