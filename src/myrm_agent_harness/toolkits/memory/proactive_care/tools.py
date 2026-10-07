"""[POS]: src/myrm_agent_harness/toolkits/memory/proactive_care/tools.py
[INPUT]: ProactiveCareRebalancingService instance.
[OUTPUT]: Meta tools exposed to AI Agent for state-aware care and proactive scheduling.
"""

from myrm_agent_harness.toolkits.memory.proactive_care.models import (
    CareNotification,
    ScheduleRebalancePlan,
    ScheduleTaskItem,
    VitalityAssessmentReport,
)
from myrm_agent_harness.toolkits.memory.proactive_care.service import (
    ProactiveCareRebalancingService,
)


class ProactiveCareMetaTools:
    """Agent meta tools for evaluating human physical state and initiating proactive care."""

    def __init__(self, service: ProactiveCareRebalancingService) -> None:
        self._service = service

    def evaluate_user_vitality(self, user_id: str = "default_user") -> VitalityAssessmentReport:
        """Evaluate user vitality index and fatigue level based on health telemetries and dialog cues."""
        return self._service.evaluate_vitality(user_id=user_id)

    def record_conversational_fatigue_cue(
        self, cue_text: str, user_id: str = "default_user"
    ) -> dict[str, str | bool]:
        """Record subtle fatigue/late-night signals mentioned by user during normal conversation."""
        self._service.record_conversational_cue(cue_text=cue_text, user_id=user_id)
        return {"status": True, "recorded_cue": cue_text}

    def rebalance_schedule_proactively(
        self,
        tasks: list[dict[str, str | int | bool]],
        user_id: str = "default_user",
        force_notify: bool = False,
    ) -> dict[str, ScheduleRebalancePlan | CareNotification | None]:
        """Proactively scale down flexible schedule load and generate empathetic care notification."""
        task_items: list[ScheduleTaskItem] = []
        for t in tasks:
            task_items.append(
                ScheduleTaskItem(
                    task_id=str(t.get("task_id", "")),
                    title=str(t.get("title", "")),
                    scheduled_date=str(t.get("scheduled_date", "")),
                    intensity_level=int(t.get("intensity_level", 3)),
                    category=str(t.get("category", "general")),
                    is_flexible=bool(t.get("is_flexible", True)),
                    original_duration_minutes=int(t.get("original_duration_minutes", 60)),
                    adjusted_duration_minutes=int(t.get("adjusted_duration_minutes", 60)),
                    status=str(t.get("status", "active")),
                )
            )

        plan, notif = self._service.rebalance_schedule_and_care(
            tasks=task_items,
            user_id=user_id,
            force_notify=force_notify,
        )
        return {
            "rebalance_plan": plan,
            "care_notification": notif,
        }
