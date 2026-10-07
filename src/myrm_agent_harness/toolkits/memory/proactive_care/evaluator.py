"""[POS]: src/myrm_agent_harness/toolkits/memory/proactive_care/evaluator.py
[INPUT]: HealthMetricsRecord lists and conversational cue strings.
[OUTPUT]: Multi-modal VitalityAssessmentReport and categorized fatigue level.
"""

import time
import uuid

from myrm_agent_harness.toolkits.memory.proactive_care.models import (
    FatigueLevelKind,
    HealthMetricsRecord,
    VitalityAssessmentReport,
)

FATIGUE_KEYWORDS = (
    "熬夜",
    "通宵",
    "加班",
    "头痛",
    "头疼",
    "好累",
    "太累",
    "乏力",
    "精疲力竭",
    "失眠",
    "睡不着",
    "困死",
    "透支",
    "exhausted",
    "tired",
    "insomnia",
    "stay up",
)


class VitalityAndFatigueEvaluator:
    """Multi-modal vitality assessor fusing hardware telemetry and conversational cues."""

    def evaluate(
        self,
        health_records: list[HealthMetricsRecord],
        conversational_cues: list[str],
        user_id: str = "default_user",
    ) -> VitalityAssessmentReport:
        """Evaluate multi-modal vitality index and synthesize causality factors."""
        score = 1.0
        causal_factors: list[str] = []
        matched_cues: list[str] = []

        if health_records:
            avg_sleep = sum(r.sleep_duration_hours for r in health_records) / len(health_records)
            avg_deep_ratio = sum(r.deep_sleep_ratio for r in health_records) / len(health_records)
            avg_heart_rate = sum(r.resting_heart_rate for r in health_records) / len(health_records)
            avg_steps = sum(r.daily_steps for r in health_records) / len(health_records)

            if avg_sleep < 5.0:
                score -= 0.40
                causal_factors.append(f"连续平均睡眠严重不足 (仅 {avg_sleep:.1f} 小时)")
            elif avg_sleep < 6.0:
                score -= 0.25
                causal_factors.append(f"平均睡眠时长偏短 ({avg_sleep:.1f} 小时)")
            elif avg_sleep < 7.0:
                score -= 0.10
                causal_factors.append(f"睡眠偏少 ({avg_sleep:.1f} 小时)")

            if avg_deep_ratio < 0.12:
                score -= 0.10
                causal_factors.append(f"深睡眠比例偏低 (仅 {avg_deep_ratio * 100:.1f}%)")

            if avg_heart_rate > 78:
                score -= 0.15
                causal_factors.append(f"静息心率偏高 ({avg_heart_rate:.0f} bpm)，交感神经过度兴奋")

            if avg_steps < 2500:
                score -= 0.05
                causal_factors.append(f"活动步数严重不足 ({avg_steps:.0f} 步)，长期久坐缺乏血氧循环")
        else:
            causal_factors.append("缺乏连续客观硬件体征数据，依赖对话语义推断")

        # 对话疲劳线索加权
        cue_penalty = 0.0
        for cue in conversational_cues:
            lowered = cue.lower()
            hit_words = [kw for kw in FATIGUE_KEYWORDS if kw in lowered]
            if hit_words:
                matched_cues.append(f"{cue} (触发: {', '.join(hit_words)})")
                cue_penalty += 0.10

        capped_cue_penalty = min(cue_penalty, 0.35)
        if capped_cue_penalty > 0.0:
            score -= capped_cue_penalty
            causal_factors.append(f"对话中随口提及高频疲劳/熬夜口癖 ({len(matched_cues)} 处线索)")

        clamped_score = max(0.05, min(1.0, round(score, 2)))

        if clamped_score >= 0.75:
            level = FatigueLevelKind.NORMAL
            recs = [
                "状态充沛，建议按原定日程高效推进核心目标。",
                "保持规律作息与足量饮水。",
            ]
        elif clamped_score >= 0.45:
            level = FatigueLevelKind.MILD_FATIGUE
            recs = [
                "检测到轻度生理疲劳，建议将本周弹性任务与高强度训练下调 30%。",
                "今晚提早 45 分钟就寝，减少睡前蓝光暴露。",
                "核心重要任务保留，但适当放缓节奏，留足休整时间。",
            ]
        else:
            level = FatigueLevelKind.SEVERE_OVERDRAW
            recs = [
                "检测到身体处于严重透支状态，建议全面启动弹性排期重塑，任务负荷调轻 50%。",
                "强力建议推迟非紧急高耗能活动与极限力量训练。",
                "安排 20-30 分钟午间小憩，补充温水并保证今晚至少 8 小时优质睡眠。",
            ]

        return VitalityAssessmentReport(
            assessment_id=f"vitality-{uuid.uuid4().hex[:10]}",
            user_id=user_id,
            timestamp=time.time(),
            vitality_score=clamped_score,
            fatigue_level=level,
            causal_factors=causal_factors,
            conversational_cues=matched_cues,
            recommendations=recs,
        )
