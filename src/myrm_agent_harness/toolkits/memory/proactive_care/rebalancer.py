"""[POS]: src/myrm_agent_harness/toolkits/memory/proactive_care/rebalancer.py
[INPUT]: VitalityAssessmentReport and list of ScheduleTaskItem.
[OUTPUT]: ScheduleRebalancePlan and empathetic CareNotification before user asks.
"""

import time
import uuid

from myrm_agent_harness.toolkits.memory.proactive_care.models import (
    CareNotification,
    FatigueLevelKind,
    ScheduleRebalancePlan,
    ScheduleTaskItem,
    VitalityAssessmentReport,
)


class ProactiveScheduleRebalancer:
    """Acts-Before-You-Ask dynamic schedule scaler and high-empathy care generator."""

    def rebalance(
        self,
        report: VitalityAssessmentReport,
        tasks: list[ScheduleTaskItem],
        user_id: str = "default_user",
    ) -> tuple[ScheduleRebalancePlan, CareNotification]:
        """Dynamically rescale flexible schedule tasks and synthesize proactive care notification."""
        fatigue_level = report.fatigue_level
        modified_tasks: list[ScheduleTaskItem] = []

        if fatigue_level == FatigueLevelKind.NORMAL:
            load_reduction_ratio = 0.0
            summary = "用户生理与精神状态饱满，日程保持原样，无需弹性调轻。"
            for t in tasks:
                t_copy = t.model_copy()
                t_copy.adjusted_duration_minutes = t_copy.original_duration_minutes
                modified_tasks.append(t_copy)

            notification = CareNotification(
                notification_id=f"care-{uuid.uuid4().hex[:10]}",
                user_id=user_id,
                timestamp=time.time(),
                fatigue_level=FatigueLevelKind.NORMAL,
                title="今日状态充沛，扬帆起航 🚀",
                content_message="监测到你作息规律、精神状态良好。今日排期按原计划全速推进，祝你有充实而美好的一天！",
                suggested_actions=["按时推进核心任务", "保持足量水分摄入"],
                is_read=False,
            )

        elif fatigue_level == FatigueLevelKind.MILD_FATIGUE:
            load_reduction_ratio = 0.30
            summary = "检测到轻度疲劳与睡眠不足，对弹性任务与中高强度训练主动调轻 30% 负荷。"
            for t in tasks:
                t_copy = t.model_copy()
                if t_copy.is_flexible and t_copy.intensity_level >= 2:
                    t_copy.adjusted_duration_minutes = max(
                        15, round(t_copy.original_duration_minutes * 0.70)
                    )
                    t_copy.intensity_level = max(1, t_copy.intensity_level - 1)
                else:
                    t_copy.adjusted_duration_minutes = t_copy.original_duration_minutes
                modified_tasks.append(t_copy)

            cues_snippet = (
                f"（提及了: {report.conversational_cues[0].split(' ')[0]}）"
                if report.conversational_cues
                else ""
            )
            notification = CareNotification(
                notification_id=f"care-{uuid.uuid4().hex[:10]}",
                user_id=user_id,
                timestamp=time.time(),
                fatigue_level=FatigueLevelKind.MILD_FATIGUE,
                title="早安！今天帮你稍微放缓了节奏 🌿",
                content_message=(
                    f"看到你这两天睡眠略有不足{cues_snippet}，"
                    "我已先于你开口，主动帮你把今日与本周的弹性训练计划调轻了 30%。"
                    "重要事情依然稳步推进，但身体永远在第一位，被惦记着的感觉真好，今晚争取早点休息～"
                ),
                suggested_actions=[
                    "弹性任务时长已自动缩减 30%",
                    "今晚提前 45 分钟就寝",
                    "傍晚安排 15 分钟户外散步",
                ],
                is_read=False,
            )

        else:  # SEVERE_OVERDRAW
            load_reduction_ratio = 0.50
            summary = "检测到严重生理透支与连环熬夜，全面启动弹性排期重塑，任务负荷强制下调 50%。"
            for t in tasks:
                t_copy = t.model_copy()
                if t_copy.is_flexible:
                    t_copy.adjusted_duration_minutes = max(
                        15, round(t_copy.original_duration_minutes * 0.50)
                    )
                    t_copy.intensity_level = max(1, t_copy.intensity_level - 2)
                    if t_copy.intensity_level >= 4:
                        t_copy.status = "postponed"
                else:
                    t_copy.adjusted_duration_minutes = t_copy.original_duration_minutes
                modified_tasks.append(t_copy)

            notification = CareNotification(
                notification_id=f"care-{uuid.uuid4().hex[:10]}",
                user_id=user_id,
                timestamp=time.time(),
                fatigue_level=FatigueLevelKind.SEVERE_OVERDRAW,
                title="抱歉打扰，但你的身体真的需要喘口气了 🛌",
                content_message=(
                    "监测到你最近连续熬夜、生理指标透支明显。不用硬扛，"
                    "我已主动帮你把本周的非紧急弹性任务调轻了一半，高负荷训练已自动顺延。"
                    "模型会一直变得更聪明，但真正留得住人的是懂你。今天允许自己早点休息，放轻松！"
                ),
                suggested_actions=[
                    "非紧急弹性计划负荷已减半",
                    "极限力量/高耗能训练已暂缓",
                    "中午安排 20-30 分钟闭目小憩",
                    "今晚务必保证 8 小时优质睡眠",
                ],
                is_read=False,
            )

        plan = ScheduleRebalancePlan(
            plan_id=f"plan-{uuid.uuid4().hex[:10]}",
            user_id=user_id,
            created_at=time.time(),
            fatigue_level=fatigue_level,
            load_reduction_ratio=load_reduction_ratio,
            tasks_modified=modified_tasks,
            summary=summary,
        )

        return plan, notification
