"""从行为中涌现的注意力清单、海量通知意图过滤器与言行错位智能对照引擎。

[INPUT]
- traces: Sequence[ActionTraceEvent]
- notification: InboundNotification
- stated_intentions: Sequence[StatedIntention]

[OUTPUT]
- EmergentAttentionEngine: 核心注意力涌现与言行错位对照引擎

[POS]
- 位于 context_management/emergent_attention/emergent_attention_engine.py
"""

from collections import defaultdict
from collections.abc import Sequence
import time

from .emergent_attention_types import (
    ActionTraceEvent,
    EmergentAttentionDossier,
    EmergentAttentionItem,
    InboundNotification,
    IntentionActionDiffItem,
    IntentionActionDiffReport,
    NotificationSieveResult,
    SieveDecision,
    StatedIntention,
)

BLOCKER_KEYWORDS: tuple[str, ...] = (
    "blocker",
    "blocked",
    "failed",
    "bug",
    "stuck",
    "卡住",
    "阻碍",
    "失败",
    "报错",
    "挂起",
)


class EmergentAttentionEngine:
    """注意力清单涌现、入站消息过滤与言行错位对照引擎。"""

    def ingest_action_traces(
        self,
        traces: Sequence[ActionTraceEvent],
    ) -> EmergentAttentionDossier:
        """从用户多应用数字足迹行为轨迹中逆向涌现当前真实注意力清单。"""
        if not traces:
            return EmergentAttentionDossier(
                generated_at_epoch=time.time(),
                items=[],
                primary_focus="None",
                total_tracked_minutes=0,
            )

        project_minutes: dict[str, int] = defaultdict(int)
        project_events: dict[str, list[ActionTraceEvent]] = defaultdict(list)
        total_minutes = 0

        for event in traces:
            duration = max(1, event.duration_minutes)
            total_minutes += duration
            tags = event.project_tags or ["unclassified"]
            for tag in tags:
                clean_tag = tag.strip() or "unclassified"
                project_minutes[clean_tag] += duration
                project_events[clean_tag].append(event)

        attention_items: list[EmergentAttentionItem] = []
        for proj, mins in project_minutes.items():
            ev_list = project_events[proj]
            ev_list.sort(key=lambda x: x.timestamp_epoch, reverse=True)
            latest_ev = ev_list[0]
            last_epoch = latest_ev.timestamp_epoch

            # 探测最新进展与潜在阻碍
            key_progress = f"{latest_ev.title}: {latest_ev.summary}"
            blocker_text = "None"
            for ev in ev_list:
                combined_text = f"{ev.title} {ev.summary}".lower()
                if any(kw in combined_text for kw in BLOCKER_KEYWORDS):
                    blocker_text = f"Blocked on: {ev.title}"
                    break

            score = round(mins / total_minutes, 4) if total_minutes > 0 else 0.0
            attention_items.append(
                EmergentAttentionItem(
                    project_name=proj,
                    attention_score=score,
                    last_active_epoch=last_epoch,
                    key_progress=key_progress[:180],
                    current_blocker=blocker_text,
                    estimated_time_spent_mins=mins,
                )
            )

        # 按注意力聚焦分数降序排序
        attention_items.sort(key=lambda x: x.attention_score, reverse=True)
        primary_focus = attention_items[0].project_name if attention_items else "None"

        return EmergentAttentionDossier(
            generated_at_epoch=time.time(),
            items=attention_items,
            primary_focus=primary_focus,
            total_tracked_minutes=total_minutes,
        )

    def filter_inbound_notification(
        self,
        notification: InboundNotification,
        attention_dossier: EmergentAttentionDossier,
    ) -> NotificationSieveResult:
        """根据当前真实注意力焦点执行高信噪比入站消息智能筛查。"""
        # 紧急拦截防线：涉及审批或极高危等级通知立即放行
        if notification.requires_approval or notification.urgency_hint.lower() in ("critical", "emergency"):
            return NotificationSieveResult(
                notification_id=notification.notification_id,
                decision=SieveDecision.DELIVER_IMMEDIATELY,
                relevance_score=1.0,
                route_reason="Requires mandatory approval or marked critical urgency",
            )

        target_tag = notification.project_tag.strip()
        matched_item: EmergentAttentionItem | None = None
        for it in attention_dossier.items:
            if it.project_name.lower() == target_tag.lower():
                matched_item = it
                break

        # 核心注意力焦点匹配
        if matched_item:
            # 属于第一焦点项目或高注意力分配 (>= 0.25)
            if matched_item.project_name == attention_dossier.primary_focus or matched_item.attention_score >= 0.25:
                return NotificationSieveResult(
                    notification_id=notification.notification_id,
                    decision=SieveDecision.DELIVER_IMMEDIATELY,
                    relevance_score=round(matched_item.attention_score, 2),
                    route_reason=f"Matches current active focus [{matched_item.project_name}]",
                )
            # 中等相关度：批次摘要归档，不打碎即时心流
            if matched_item.attention_score >= 0.08:
                return NotificationSieveResult(
                    notification_id=notification.notification_id,
                    decision=SieveDecision.DIGEST_BATCH,
                    relevance_score=round(matched_item.attention_score, 2),
                    route_reason=f"Secondary interest in [{matched_item.project_name}], batched to digest",
                )

        # 低注意力或未关联噪声：静默归档
        return NotificationSieveResult(
            notification_id=notification.notification_id,
            decision=SieveDecision.SILENT_ARCHIVE,
            relevance_score=0.05,
            route_reason="Unrelated or low attention project, silently archived to pool",
        )

    def analyze_intention_action_diff(
        self,
        stated_intentions: Sequence[StatedIntention],
        dossier: EmergentAttentionDossier,
    ) -> IntentionActionDiffReport:
        """自动化分析用户口头设定的优先级与实际精力分配的言行错位。"""
        diff_items: list[IntentionActionDiffItem] = []
        warnings: list[str] = []
        total_tracked = max(1, dossier.total_tracked_minutes)

        actual_map: dict[str, float] = {}
        for item in dossier.items:
            pct = (item.estimated_time_spent_mins / total_tracked) * 100.0
            actual_map[item.project_name.lower()] = round(pct, 2)

        total_drift = 0.0

        for intention in stated_intentions:
            proj_key = intention.project_name.lower()
            actual_pct = actual_map.get(proj_key, 0.0)
            diff = round(actual_pct - intention.target_percentage, 2)
            total_drift += abs(diff)

            is_neglected = diff < -15.0
            is_over_invested = diff > 20.0

            comment = "On track with stated intention"
            if is_neglected:
                comment = (
                    f"Neglected focus: Planned {intention.target_percentage}% but only spent "
                    f"{actual_pct}% (-{abs(diff)}%)"
                )
                warnings.append(f"[{intention.project_name}] 目标严重欠投（计划 {intention.target_percentage}%, 实际仅 {actual_pct}%）")
            elif is_over_invested:
                comment = (
                    f"Over-invested drift: Planned {intention.target_percentage}% but consumed "
                    f"{actual_pct}% (+{diff}%)"
                )
                warnings.append(f"[{intention.project_name}] 发生精力漂移（计划 {intention.target_percentage}%, 实际消耗 {actual_pct}%）")

            diff_items.append(
                IntentionActionDiffItem(
                    project_name=intention.project_name,
                    stated_percentage=intention.target_percentage,
                    actual_percentage=actual_pct,
                    diff_percentage=diff,
                    is_neglected=is_neglected,
                    is_over_invested=is_over_invested,
                    drift_comment=comment,
                )
            )

        overall_drift_index = round(total_drift / 2.0, 2)
        return IntentionActionDiffReport(
            overall_drift_index=overall_drift_index,
            items=diff_items,
            top_drift_warnings=warnings,
            analyzed_epoch=time.time(),
        )
