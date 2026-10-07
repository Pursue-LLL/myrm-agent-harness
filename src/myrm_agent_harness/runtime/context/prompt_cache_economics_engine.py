"""Prompt cache economics engine and cross-deployment HUD generator.

[INPUT]
Token usage statistics, model names, and detected drift events.

[OUTPUT]
Turn-by-turn and session-wide financial metrics, 30x savings calculations,
traffic light diagnoses, and unified HUD payloads for WebUI, Tauri, and Cloud Sandboxes.

[POS]
Core financial telemetry engine benchmarked against DeepSeek Harness 1/30 economics model.
"""

import threading
from collections.abc import Mapping

from myrm_agent_harness.runtime.context.prompt_cache_economics_types import (
    CrossDeploymentHudPayload,
    HealthTrafficLight,
    ModelPricingTier,
    SessionCacheEconomicsSummary,
    TurnCacheEconomicsRecord,
)

# Standard market rates per million tokens in USD
_DEFAULT_PRICING_TIERS: dict[str, ModelPricingTier] = {
    "deepseek-chat": ModelPricingTier(
        model_name="deepseek-chat",
        uncached_input_per_m_usd=2.00,
        cached_input_per_m_usd=0.10,
        output_per_m_usd=8.00,
    ),
    "deepseek-reasoner": ModelPricingTier(
        model_name="deepseek-reasoner",
        uncached_input_per_m_usd=4.00,
        cached_input_per_m_usd=0.14,
        output_per_m_usd=16.00,
    ),
    "claude-3-5-sonnet": ModelPricingTier(
        model_name="claude-3-5-sonnet",
        uncached_input_per_m_usd=3.00,
        cached_input_per_m_usd=0.30,
        output_per_m_usd=15.00,
    ),
    "gpt-4o": ModelPricingTier(
        model_name="gpt-4o",
        uncached_input_per_m_usd=2.50,
        cached_input_per_m_usd=1.25,
        output_per_m_usd=10.00,
    ),
}

_FALLBACK_TIER = ModelPricingTier(
    model_name="fallback-generic",
    uncached_input_per_m_usd=3.00,
    cached_input_per_m_usd=0.10,
    output_per_m_usd=10.00,
)


class PromptCacheEconomicsEngine:
    """Calculates real-time financial savings and synthesizes cross-deployment HUD states."""

    def __init__(self, custom_pricing: Mapping[str, ModelPricingTier] | None = None) -> None:
        self._lock = threading.RLock()
        self._pricing: dict[str, ModelPricingTier] = dict(_DEFAULT_PRICING_TIERS)
        if custom_pricing:
            self._pricing.update(custom_pricing)
        self._records_by_session: dict[str, list[TurnCacheEconomicsRecord]] = {}

    def get_pricing_tier(self, model_name: str) -> ModelPricingTier:
        """Find matching pricing tier or return default fallback."""
        with self._lock:
            lower = model_name.lower()
            for key, tier in self._pricing.items():
                if key in lower:
                    return tier
            return _FALLBACK_TIER

    def record_turn_usage(
        self,
        session_id: str,
        model_name: str,
        prompt_tokens: int,
        cached_tokens: int,
        completion_tokens: int,
        drift_reason: str | None = None,
    ) -> TurnCacheEconomicsRecord:
        """Record turn tokens, compute savings relative to uncached baseline, and log record."""
        with self._lock:
            tier = self.get_pricing_tier(model_name)
            safe_cached = min(cached_tokens, prompt_tokens)
            uncached_prompt = max(0, prompt_tokens - safe_cached)

            # Cost calculations
            actual_input = (
                uncached_prompt * tier.uncached_input_per_m_usd
                + safe_cached * tier.cached_input_per_m_usd
            ) / 1_000_000.0
            baseline_input = (prompt_tokens * tier.uncached_input_per_m_usd) / 1_000_000.0
            output_cost = (completion_tokens * tier.output_per_m_usd) / 1_000_000.0

            actual_cost = actual_input + output_cost
            baseline_cost = baseline_input + output_cost
            savings = max(0.0, baseline_cost - actual_cost)

            hit_rate = (safe_cached / prompt_tokens) if prompt_tokens > 0 else 0.0
            savings_ratio = (savings / baseline_cost) if baseline_cost > 0 else 0.0
            multiplier = (baseline_cost / actual_cost) if actual_cost > 0 else 1.0

            # Traffic light determination
            if hit_rate >= 0.95:
                traffic_light = HealthTrafficLight.GREEN_OPTIMAL
            elif hit_rate >= 0.60:
                traffic_light = HealthTrafficLight.YELLOW_PARTIAL
            else:
                traffic_light = HealthTrafficLight.RED_DRIFT_BREACH

            history = self._records_by_session.setdefault(session_id, [])
            turn_idx = len(history) + 1

            record = TurnCacheEconomicsRecord(
                turn_index=turn_idx,
                model_name=model_name,
                prompt_tokens=prompt_tokens,
                cached_tokens=safe_cached,
                completion_tokens=completion_tokens,
                cache_hit_rate=hit_rate,
                actual_cost_usd=actual_cost,
                baseline_uncached_cost_usd=baseline_cost,
                savings_usd=savings,
                savings_ratio=savings_ratio,
                savings_multiplier=multiplier,
                traffic_light=traffic_light,
                drift_diagnosis=drift_reason,
            )
            history.append(record)
            return record

    def get_session_summary(self, session_id: str) -> SessionCacheEconomicsSummary:
        """Aggregate all turns in a session into a lifecycle economics summary."""
        with self._lock:
            turns = self._records_by_session.get(session_id, [])
            if not turns:
                return SessionCacheEconomicsSummary(
                    session_id=session_id,
                    total_turns_count=0,
                    total_prompt_tokens=0,
                    total_cached_tokens=0,
                    total_completion_tokens=0,
                    overall_cache_hit_rate=0.0,
                    total_actual_cost_usd=0.0,
                    total_baseline_uncached_cost_usd=0.0,
                    total_savings_usd=0.0,
                    overall_savings_ratio=0.0,
                    overall_savings_multiplier=1.0,
                    dominant_traffic_light=HealthTrafficLight.RED_DRIFT_BREACH,
                )

            total_prompt = sum(t.prompt_tokens for t in turns)
            total_cached = sum(t.cached_tokens for t in turns)
            total_completion = sum(t.completion_tokens for t in turns)
            total_actual = sum(t.actual_cost_usd for t in turns)
            total_baseline = sum(t.baseline_uncached_cost_usd for t in turns)
            total_savings = sum(t.savings_usd for t in turns)

            hit_rate = (total_cached / total_prompt) if total_prompt > 0 else 0.0
            savings_ratio = (total_savings / total_baseline) if total_baseline > 0 else 0.0
            multiplier = (total_baseline / total_actual) if total_actual > 0 else 1.0

            green_count = sum(1 for t in turns if t.traffic_light == HealthTrafficLight.GREEN_OPTIMAL)
            if green_count >= (len(turns) // 2):
                dominant_light = HealthTrafficLight.GREEN_OPTIMAL
            elif hit_rate >= 0.60:
                dominant_light = HealthTrafficLight.YELLOW_PARTIAL
            else:
                dominant_light = HealthTrafficLight.RED_DRIFT_BREACH

            return SessionCacheEconomicsSummary(
                session_id=session_id,
                total_turns_count=len(turns),
                total_prompt_tokens=total_prompt,
                total_cached_tokens=total_cached,
                total_completion_tokens=total_completion,
                overall_cache_hit_rate=hit_rate,
                total_actual_cost_usd=total_actual,
                total_baseline_uncached_cost_usd=total_baseline,
                total_savings_usd=total_savings,
                overall_savings_ratio=savings_ratio,
                overall_savings_multiplier=multiplier,
                dominant_traffic_light=dominant_light,
            )

    def generate_hud_payload(self, session_id: str) -> CrossDeploymentHudPayload:
        """Synthesize unified HUD presentation payload for WebUI/Tauri/Cloud consumption."""
        summary = self.get_session_summary(session_id)
        hit_percent = round(summary.overall_cache_hit_rate * 100, 1)

        if summary.dominant_traffic_light == HealthTrafficLight.GREEN_OPTIMAL:
            badge = "🟢 极速缓存 (99%)"
            headline = f"缓存命中率 {hit_percent}% · 享受 1/30 极限低价，成本立省 {summary.overall_savings_multiplier:.1f}x"
            tips = (
                "System 前缀保持绝对不可变，KV Cache 完美复用",
                "可变状态已通过尾部增量标签安全缝合，零破坏前缀",
            )
        elif summary.dominant_traffic_light == HealthTrafficLight.YELLOW_PARTIAL:
            badge = "🟡 部分缓存命中"
            headline = f"缓存命中率 {hit_percent}% · 存在轻微尾部状态变动或工具更新"
            tips = (
                "建议通过 SessionStateDeltaEngine 统一管理可变环境变量",
                "确保动态时间戳不进入前缀 Prompt",
            )
        else:
            badge = "🔴 前缀漂移或冷启动"
            headline = f"缓存命中率 {hit_percent}% · 建议检查 System Prompt 是否发生字节变动"
            tips = (
                "检查是否中途切换了模型或修改了 System Prompt",
                "确保工具注册表的序列化顺序保持一致",
            )

        return CrossDeploymentHudPayload(
            session_id=session_id,
            traffic_light=summary.dominant_traffic_light,
            traffic_light_badge=badge,
            cache_hit_rate_percent=hit_percent,
            savings_multiplier_label=f"{summary.overall_savings_multiplier:.1f}x 便宜",
            total_savings_usd_formatted=f"${summary.total_savings_usd:.4f}",
            headline_message=headline,
            anti_drift_tips=tips,
        )
