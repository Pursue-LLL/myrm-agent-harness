"""
[INPUT]: Model name, task category, actual cost, token counts, and cache hit rates.
[OUTPUT]: CostDriftAlert detecting relative unit-cost deviations (>20%) against historical rolling baselines.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/token_economics/drift_detector.py
"""

from datetime import datetime, timezone
import threading
from typing import Dict, List, Optional, Tuple

from .models import CostDriftAlert, DriftReasonType, UnitCostBaseline


class UnitCostDriftDetector:
    """
    Maintains rolling baselines of unit cost (RMB per 1k tokens) per (model, task_category).
    Detects cost drift (>20% higher than baseline) and attributes reasons transparently.
    """

    def __init__(self, max_samples: int = 30, drift_threshold_pct: float = 20.0) -> None:
        self._lock = threading.Lock()
        self._max_samples = max_samples
        self._drift_threshold_pct = drift_threshold_pct
        self._baselines: Dict[Tuple[str, str], UnitCostBaseline] = {}

    def get_baseline(self, model_name: str, task_category: str) -> Optional[UnitCostBaseline]:
        with self._lock:
            return self._baselines.get((model_name, task_category))

    def record_and_evaluate(
        self,
        model_name: str,
        task_category: str,
        total_tokens: int,
        actual_cost_rmb: float,
        cache_hit_rate_pct: float,
        is_routed_fallback: bool = False,
    ) -> CostDriftAlert:
        with self._lock:
            key = (model_name, task_category)
            if key not in self._baselines:
                self._baselines[key] = UnitCostBaseline(
                    model_name=model_name,
                    task_category=task_category,
                    rolling_samples=[],
                    average_unit_cost_per_k=0.0,
                    sample_count=0,
                    last_updated_at=datetime.now(timezone.utc).isoformat(),
                )

            baseline_entry = self._baselines[key]
            current_unit_cost = (
                (actual_cost_rmb / total_tokens) * 1000.0 if total_tokens > 0 else 0.0
            )

            # Determine drift against baseline before appending current sample
            prev_samples = baseline_entry.rolling_samples
            has_baseline = len(prev_samples) >= 3
            baseline_avg = baseline_entry.average_unit_cost_per_k if has_baseline else current_unit_cost

            drift_pct = 0.0
            if has_baseline and baseline_avg > 0.0:
                drift_pct = round(((current_unit_cost - baseline_avg) / baseline_avg) * 100.0, 2)

            is_significant = has_baseline and (drift_pct >= self._drift_threshold_pct)

            # Attribution analysis
            reason = DriftReasonType.NORMAL
            explanation = "单位成本在历史基线合理波动区间内。"

            if is_significant:
                if is_routed_fallback:
                    reason = DriftReasonType.ROUTING_FALLBACK
                    explanation = f"检测到模型发生降级路由重定向至 {model_name}，导致单位成本上涨 {drift_pct}%。"
                elif cache_hit_rate_pct < 50.0:
                    reason = DriftReasonType.CACHE_HIT_DEGRADED
                    explanation = f"Prompt 缓存击穿劣化（当前命中率仅 {cache_hit_rate_pct}%），导致单位成本较历史基线显著增加 {drift_pct}%。"
                elif total_tokens > 40_000:
                    reason = DriftReasonType.PROMPT_BLOAT
                    explanation = f"单轮上下文极度膨胀（{total_tokens} Tokens），导致边际生成成本上涨 {drift_pct}%。"
                else:
                    reason = DriftReasonType.UPSTREAM_PRICE_INCREASE
                    explanation = f"缓存命中率正常，但单位成本激增 {drift_pct}%，判定为上游供应商取消补贴或调整定价策略。"

            # Update rolling baseline
            prev_samples.append(current_unit_cost)
            if len(prev_samples) > self._max_samples:
                prev_samples.pop(0)

            baseline_entry.sample_count = len(prev_samples)
            baseline_entry.average_unit_cost_per_k = round(
                sum(prev_samples) / len(prev_samples), 6
            )
            baseline_entry.last_updated_at = datetime.now(timezone.utc).isoformat()

            return CostDriftAlert(
                task_category=task_category,
                model_name=model_name,
                current_unit_cost_per_k=round(current_unit_cost, 6),
                baseline_unit_cost_per_k=round(baseline_avg, 6),
                drift_percentage=drift_pct,
                is_significant_drift=is_significant,
                reason=reason,
                explanation=explanation,
            )
