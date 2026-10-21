"""
[INPUT]:
- myrm_agent_harness.observability.rate_limit_governor::QuotaHeaderSniffer
- myrm_agent_harness.observability.rate_limit_governor::ProactivePacingGovernor
- myrm_agent_harness.observability.rate_limit_governor::SubagentQuotaSlicer
- myrm_agent_harness.observability.rate_limit_governor::models

[OUTPUT]:
- Pytest unit tests verifying HTTP header sniffing, proactive traffic shaping, zero-429 pacing, and subagent quota slicing.

[POS]:
tests/observability/test_rate_limit_governor.py — 客户端主动限流预测阀门与自适应配额调度单元测试。
"""

import pytest

from myrm_agent_harness.observability.rate_limit_governor import (
    ModelRateLimitConfig,
    PacingAction,
    ProactivePacingGovernor,
    QuotaHeaderSniffer,
    SubagentQuotaSlicer,
)


def test_quota_header_sniffer_multi_provider() -> None:
    # 1. 模拟 OpenAI 响应头
    openai_headers = {
        "x-ratelimit-remaining-tokens": "75000",
        "x-ratelimit-reset-tokens": "250ms",
        "x-ratelimit-remaining-requests": "58",
        "x-ratelimit-reset-requests": "1.2s",
    }
    s_openai = QuotaHeaderSniffer.sniff("gpt-4o", openai_headers)
    assert s_openai.remaining_tokens == 75000
    assert s_openai.reset_tokens_seconds == 0.25
    assert s_openai.remaining_requests == 58
    assert s_openai.reset_requests_seconds == 1.2

    # 2. 模拟 Anthropic 响应头
    anthropic_headers = {
        "anthropic-ratelimit-tokens-remaining": "32000",
        "anthropic-ratelimit-tokens-reset": "2s",
        "retry-after": "5",
    }
    s_anthropic = QuotaHeaderSniffer.sniff("claude-3-5-sonnet", anthropic_headers)
    assert s_anthropic.remaining_tokens == 32000
    assert s_anthropic.reset_tokens_seconds == 2.0
    assert s_anthropic.retry_after_seconds == 5.0


def test_proactive_pacing_governor_traffic_shaping() -> None:
    custom_cfg = {
        "claude-3-5-sonnet": ModelRateLimitConfig(
            model_name="claude-3-5-sonnet",
            max_rpm=10,
            max_tpm=10_000,
            safe_watermark_pct=85.0,
        )
    }
    governor = ProactivePacingGovernor(custom_configs=custom_cfg)

    # 1. 初始状态：低水位健康放行
    decision_pass = governor.evaluate_and_pace("claude-3-5-sonnet", estimated_prompt_tokens=2_000)
    assert decision_pass.action == PacingAction.IMMEDIATE_PASS
    assert decision_pass.delay_ms == 0
    assert decision_pass.tpm_watermark_pct == 20.0

    # 记录该次消耗
    governor.record_usage("claude-3-5-sonnet", actual_tokens=2_000)

    # 2. 累加消耗至 88% 水位 (已消耗 2,000，新请求预计 6,800 => 8,800/10,000 = 88%)
    decision_pace = governor.evaluate_and_pace("claude-3-5-sonnet", estimated_prompt_tokens=6_800)
    assert decision_pace.action == PacingAction.MICRO_SLEEP_PACED
    assert decision_pace.delay_ms == 350
    assert decision_pace.tpm_watermark_pct == 88.0

    # 3. 超过 100% 触发降级或排队
    # 3a. 配置了 fallback 模型
    decision_fallback = governor.evaluate_and_pace(
        "claude-3-5-sonnet",
        estimated_prompt_tokens=9_000,
        fallback_model="claude-3-5-haiku",
    )
    assert decision_fallback.action == PacingAction.FALLBACK_DOWNGRADE
    assert decision_fallback.target_model_or_fallback == "claude-3-5-haiku"

    # 3b. 未配置 fallback 模型，触发排队等待
    decision_queue = governor.evaluate_and_pace(
        "claude-3-5-sonnet",
        estimated_prompt_tokens=9_000,
    )
    assert decision_queue.action == PacingAction.QUEUE_WAIT
    assert decision_queue.delay_ms > 0

    # 4. 查验实时仪表状态
    status = governor.get_live_status("claude-3-5-sonnet")
    assert status.smoothed_request_count >= 1
    assert status.prevented_429_count >= 1


def test_subagent_quota_slicer_isolation() -> None:
    slicer = SubagentQuotaSlicer()

    # 1. 为同一 workspace 下两个并发子 Agent 切割总计 40,000 TPM
    slice_a = slicer.allocate_slice("ws-alpha", "subagent-1", total_available_tpm=40_000, concurrency_count=2)
    slice_b = slicer.allocate_slice("ws-alpha", "subagent-2", total_available_tpm=40_000, concurrency_count=2)

    assert slice_a.allocated_tpm_share == 20_000
    assert slice_b.allocated_tpm_share == 20_000

    # 2. subagent-1 贪婪消耗 22,000 tokens，触发限流
    updated_a = slicer.record_consumption("ws-alpha", "subagent-1", tokens=22_000)
    assert updated_a.is_throttled is True
    assert updated_a.remaining_tokens_in_window == 0
    assert slicer.is_subagent_throttled("ws-alpha", "subagent-1") is True

    # 3. subagent-2 仅消耗 5,000 tokens，保持健康不受干扰
    updated_b = slicer.record_consumption("ws-alpha", "subagent-2", tokens=5_000)
    assert updated_b.is_throttled is False
    assert updated_b.remaining_tokens_in_window == 15_000
    assert slicer.is_subagent_throttled("ws-alpha", "subagent-2") is False

    # 4. 重置窗口
    slicer.reset_window("ws-alpha")
    assert slicer.is_subagent_throttled("ws-alpha", "subagent-1") is False
