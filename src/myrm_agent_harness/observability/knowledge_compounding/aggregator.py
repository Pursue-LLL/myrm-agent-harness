"""
[INPUT]: Raw metrics for repeated errors, memory hit rate, human corrections, first-pass success, and stale knowledge.
[OUTPUT]: Evaluated KnowledgeCompoundingHealthSnapshot with health status, overall score, and regression alerts.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/knowledge_compounding/aggregator.py
"""

from datetime import datetime, timezone
import math
from typing import Dict, List, Optional

from .models import (
    CompoundingMetricName,
    CompoundingMetricPoint,
    KnowledgeCompoundingHealthSnapshot,
    MetricHealthStatus,
)


class KnowledgeCompoundingAggregator:
    """Read-only deterministic aggregator for evaluating agent knowledge compounding efficacy."""

    def __init__(self) -> None:
        pass

    def evaluate(
        self,
        repeated_error_rate_pct: float = 3.5,
        knowledge_hit_rate_pct: float = 68.0,
        human_corrections_count: int = 4,
        first_pass_success_rate_pct: float = 88.5,
        stale_knowledge_ratio_pct: float = 8.0,
        window_days: int = 30,
    ) -> KnowledgeCompoundingHealthSnapshot:
        """Evaluate and aggregate 5 closure metrics into an immutable health scorecard."""

        # 1. 约束数值在合理范围
        rep_err = max(0.0, min(100.0, float(repeated_error_rate_pct)))
        hit_rate = max(0.0, min(100.0, float(knowledge_hit_rate_pct)))
        corrections = max(0, int(human_corrections_count))
        pass_rate = max(0.0, min(100.0, float(first_pass_success_rate_pct)))
        stale_ratio = max(0.0, min(100.0, float(stale_knowledge_ratio_pct)))

        alerts: List[str] = []

        # 2. 逐项评估状态与基线
        # 指标 1: 重复错误率 (越低越好, 目标 <= 5%)
        if rep_err <= 5.0:
            rep_status = MetricHealthStatus.HEALTHY
        elif rep_err <= 15.0:
            rep_status = MetricHealthStatus.WARNING
        else:
            rep_status = MetricHealthStatus.CRITICAL
            alerts.append(f"重复错误率偏高 ({rep_err:.1f}%)，提示已知错误在后续任务中多次复现，经验沉淀闭环存在阻碍")

        point_repeated_error = CompoundingMetricPoint(
            name=CompoundingMetricName.REPEATED_ERROR_RATE,
            value=rep_err,
            unit="%",
            status=rep_status,
            benchmark_threshold=5.0,
            description="同类任务失败与死循环在后续执行中的复发比率",
            data_source_origin="loop_guard + failure_clustering",
        )

        # 指标 2: 知识命中率 (越高越好, 目标 >= 60%)
        if hit_rate >= 60.0:
            hit_status = MetricHealthStatus.HEALTHY
        elif hit_rate >= 40.0:
            hit_status = MetricHealthStatus.WARNING
        else:
            hit_status = MetricHealthStatus.CRITICAL
            alerts.append(f"跨会话知识命中率偏低 ({hit_rate:.1f}%)，历史沉淀知识未充分被实际任务检索召回")

        point_knowledge_hit = CompoundingMetricPoint(
            name=CompoundingMetricName.KNOWLEDGE_HIT_RATE,
            value=hit_rate,
            unit="%",
            status=hit_status,
            benchmark_threshold=60.0,
            description="跨会话任务决策中有效召回既往经验与沉淀记忆的占比",
            data_source_origin="memory.metrics::cross_session_hit_rate",
        )

        # 指标 3: 人工纠正次数 (越低越好, 目标 <= 5 次)
        if corrections <= 5:
            corr_status = MetricHealthStatus.HEALTHY
        elif corrections <= 15:
            corr_status = MetricHealthStatus.WARNING
        else:
            corr_status = MetricHealthStatus.CRITICAL
            alerts.append(f"人工纠正与打回重做频次过高 ({corrections} 次)，需要关注模型决策与用户期望的偏离度")

        point_corrections = CompoundingMetricPoint(
            name=CompoundingMetricName.HUMAN_CORRECTIONS_COUNT,
            value=float(corrections),
            unit="次",
            status=corr_status,
            benchmark_threshold=5.0,
            description="周期内因产出质量不达标触发人工介入修改与纠偏的累计频次",
            data_source_origin="coordination_friction + memory.blind_spot",
        )

        # 指标 4: 任务一次通过率 (越高越好, 目标 >= 85%)
        if pass_rate >= 85.0:
            pass_status = MetricHealthStatus.HEALTHY
        elif pass_rate >= 70.0:
            pass_status = MetricHealthStatus.WARNING
        else:
            pass_status = MetricHealthStatus.CRITICAL
            alerts.append(f"任务一次通过率低于基线 ({pass_rate:.1f}%)，交付存在较多二次返工重试")

        point_first_pass = CompoundingMetricPoint(
            name=CompoundingMetricName.FIRST_PASS_SUCCESS_RATE,
            value=pass_rate,
            unit="%",
            status=pass_status,
            benchmark_threshold=85.0,
            description="未经历多次返工重试即顺利通过验收的端到端任务占比",
            data_source_origin="eval.protocols::avg_pass_rate",
        )

        # 指标 5: 过期知识占比 (越低越好, 目标 <= 10%)
        if stale_ratio <= 10.0:
            stale_status = MetricHealthStatus.HEALTHY
        elif stale_ratio <= 25.0:
            stale_status = MetricHealthStatus.WARNING
        else:
            stale_status = MetricHealthStatus.CRITICAL
            alerts.append(f"过期与被忽视知识占比达到 {stale_ratio:.1f}%，知识库存在堆积与腐化风险")

        point_stale = CompoundingMetricPoint(
            name=CompoundingMetricName.STALE_KNOWLEDGE_RATIO,
            value=stale_ratio,
            unit="%",
            status=stale_status,
            benchmark_threshold=10.0,
            description="长期未被引用、被覆写废弃或语义置信度严重衰减的记忆条目占比",
            data_source_origin="memory.health::detect_neglected",
        )

        # 3. 计算加权复合健康得分 (0 - 100)
        # 一次通过率权重 25%
        score_pass = min(100.0, (pass_rate / 85.0) * 100.0) * 0.25
        # 知识命中率权重 25%
        score_hit = min(100.0, (hit_rate / 60.0) * 100.0) * 0.25
        # 重复错误率权重 20% (逆向指标: 0% 满分, 20% 0分)
        score_rep = max(0.0, (1.0 - (rep_err / 20.0)) * 100.0) * 0.20
        # 过期知识占比权重 15% (逆向指标: 0% 满分, 35% 0分)
        score_stale = max(0.0, (1.0 - (stale_ratio / 35.0)) * 100.0) * 0.15
        # 人工纠正次数权重 15% (逆向指标: <=5 满分, >=25 0分)
        score_corr = (
            100.0 if corrections <= 5
            else max(0.0, (1.0 - ((corrections - 5) / 20.0)) * 100.0)
        ) * 0.15

        overall_score = round(score_pass + score_hit + score_rep + score_stale + score_corr, 1)
        overall_score = max(0.0, min(100.0, overall_score))

        # 4. 判定复利阶梯层级
        if overall_score >= 85.0:
            tier = "HIGHLY_COMPOUNDING"
        elif overall_score >= 70.0:
            tier = "STEADY_GROWTH"
        elif overall_score >= 50.0:
            tier = "EARLY_PHASE"
        else:
            tier = "REGRESSING"

        metrics_map: Dict[str, CompoundingMetricPoint] = {
            CompoundingMetricName.REPEATED_ERROR_RATE.value: point_repeated_error,
            CompoundingMetricName.KNOWLEDGE_HIT_RATE.value: point_knowledge_hit,
            CompoundingMetricName.HUMAN_CORRECTIONS_COUNT.value: point_corrections,
            CompoundingMetricName.FIRST_PASS_SUCCESS_RATE.value: point_first_pass,
            CompoundingMetricName.STALE_KNOWLEDGE_RATIO.value: point_stale,
        }

        evaluated_at = datetime.now(timezone.utc).isoformat()

        return KnowledgeCompoundingHealthSnapshot(
            overall_score=overall_score,
            compounding_tier=tier,
            metrics=metrics_map,
            regression_alerts=alerts,
            evaluated_at=evaluated_at,
            window_days=window_days,
        )
