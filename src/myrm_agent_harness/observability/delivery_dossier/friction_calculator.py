"""
[INPUT]: Skill execution records with model names, execution modes, acceptance verdicts, and wasted tokens.
[OUTPUT]: Stratified AssetFrictionMetric evaluations classifying core efficient vs friction assassin assets.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/delivery_dossier/friction_calculator.py
"""

from collections import defaultdict
import threading
from typing import Dict, List, NamedTuple, Tuple

from .models import AssetFrictionMetric, AssetHealthTag, ExecutionMode


class _TrialSample(NamedTuple):
    accepted: bool
    retries: int
    rework: bool
    wasted_tokens: int
    baseline_tokens: int


class AssetFrictionCalculator:
    """
    Evaluates true asset delivery efficacy and friction index stratified by
    (skill_id, model_name, execution_mode) to prevent unstratified cross-model pollution.
    """

    def __init__(self, min_samples_threshold: int = 3) -> None:
        self._lock = threading.Lock()
        self._min_samples = min_samples_threshold
        self._samples: Dict[Tuple[str, str, ExecutionMode], List[_TrialSample]] = defaultdict(list)

    def record_trial(
        self,
        skill_id: str,
        model_name: str,
        execution_mode: ExecutionMode,
        accepted: bool,
        retries: int = 0,
        rework: bool = False,
        wasted_tokens: int = 0,
        baseline_tokens: int = 1000,
    ) -> None:
        with self._lock:
            key = (skill_id, model_name, execution_mode)
            sample = _TrialSample(
                accepted=accepted,
                retries=max(0, retries),
                rework=rework,
                wasted_tokens=max(0, wasted_tokens),
                baseline_tokens=max(1, baseline_tokens),
            )
            self._samples[key].append(sample)

    def evaluate_asset(
        self,
        skill_id: str,
        model_name: str,
        execution_mode: ExecutionMode,
    ) -> AssetFrictionMetric:
        with self._lock:
            key = (skill_id, model_name, execution_mode)
            samples = self._samples.get(key, [])

            sample_count = len(samples)
            if sample_count < self._min_samples:
                return AssetFrictionMetric(
                    skill_id=skill_id,
                    model_name=model_name,
                    execution_mode=execution_mode,
                    sample_count=sample_count,
                    true_efficacy_rate_pct=0.0,
                    friction_index=0.0,
                    total_wasted_tokens=0,
                    rework_count=0,
                    retry_count=0,
                    health_tag=AssetHealthTag.SAMPLE_INSUFFICIENT,
                    governance_advice=f"当前仅采集到 {sample_count} 个样本（门槛 {self._min_samples}），样本量不足，暂不作定论。",
                )

            accepted_count = sum(1 for s in samples if s.accepted)
            total_retries = sum(s.retries for s in samples)
            total_rework = sum(1 for s in samples if s.rework)
            total_wasted = sum(s.wasted_tokens for s in samples)
            total_baseline = sum(s.baseline_tokens for s in samples)

            true_efficacy = round((accepted_count / sample_count) * 100.0, 2)

            # Friction index = (retries * 500 + rework * 2000 + wasted_tokens) / max(1, total_baseline)
            friction_cost = (total_retries * 500) + (total_rework * 2000) + total_wasted
            friction_index = round(friction_cost / max(1.0, float(total_baseline)), 4)

            # Health classification
            if true_efficacy >= 80.0 and friction_index <= 0.25:
                health_tag = AssetHealthTag.CORE_EFFICIENT
                advice = "🌟 核心高效资产：采纳率高且极低返工损耗，建议优先全场景推广。"
            elif friction_index >= 0.60 or true_efficacy <= 40.0:
                health_tag = AssetHealthTag.FRICTION_ASSASSIN
                advice = "⚠️ 摩擦刺客资产：返工率高或存在大量重试死循环浪费，建议重构提示词或降级下线。"
            else:
                health_tag = AssetHealthTag.NORMAL
                advice = "资产效能处于正常基线区间，建议持续观察。"

            return AssetFrictionMetric(
                skill_id=skill_id,
                model_name=model_name,
                execution_mode=execution_mode,
                sample_count=sample_count,
                true_efficacy_rate_pct=true_efficacy,
                friction_index=friction_index,
                total_wasted_tokens=total_wasted,
                rework_count=total_rework,
                retry_count=total_retries,
                health_tag=health_tag,
                governance_advice=advice,
            )

    def list_all_assets(self) -> List[AssetFrictionMetric]:
        with self._lock:
            keys = list(self._samples.keys())
        return [self.evaluate_asset(k[0], k[1], k[2]) for k in keys]
