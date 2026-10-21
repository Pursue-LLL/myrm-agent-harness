"""
[INPUT]: Classified visit events, page contents, and funnel conversion transitions.
[OUTPUT]: Aggregated AgentTrafficSummary reports, funnel statistics, and root-cause distributions.
[POS]: myrm-agent-harness/src/myrm_agent_harness/observability/agentic_traffic/analytics_engine.py
"""

from collections import Counter
from datetime import datetime, timezone
import threading
from typing import Dict, List, Optional

from .abandonment_sentinel import AgentAbandonmentSentinel
from .models import (
    AbandonmentReason,
    AgentTrafficSummary,
    AgentType,
    AgentVisitRecord,
    FunnelStage,
)
from .traffic_classifier import AgentTrafficClassifier


class AgenticTrafficAnalyticsEngine:
    """
    Core analytics aggregator for AI coding agent visitors, tracking conversion funnels,
    traffic distributions, and silent judgment abandonment reasons.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._classifier = AgentTrafficClassifier()
        self._sentinel = AgentAbandonmentSentinel()
        self._visits: List[AgentVisitRecord] = []

    def record_visit(
        self,
        visit_id: str,
        user_agent: str,
        target_path: str,
        headers: Optional[Dict[str, str]] = None,
        duration_ms: float = 0.0,
        status_code: int = 200,
        page_content: Optional[str] = None,
        has_llms_txt_declared: bool = False,
    ) -> AgentVisitRecord:
        agent_type, is_agent, confidence = self._classifier.classify_request(
            user_agent=user_agent,
            headers=headers,
            duration_ms=duration_ms,
        )

        abandonment_reasons: List[AbandonmentReason] = []
        funnel_stage = FunnelStage.DISCOVERED

        if is_agent:
            if page_content is not None:
                diag = self._sentinel.diagnose_page(
                    path=target_path,
                    content=page_content,
                    has_llms_txt_declared=has_llms_txt_declared,
                )
                abandonment_reasons = diag.abandonment_reasons

                if diag.aeo_score >= 80:
                    funnel_stage = FunnelStage.CONTEXT_ABSORBED
                else:
                    funnel_stage = FunnelStage.DISCOVERED

            # Check if calling sandbox or API endpoints
            if "/api/" in target_path or "/sandbox/" in target_path or "/v1/" in target_path:
                funnel_stage = FunnelStage.SANDBOX_PROBED
            if duration_ms > 2000.0 and status_code == 200:
                funnel_stage = FunnelStage.ADOPTED
        else:
            abandonment_reasons = [AbandonmentReason.NONE]

        now_iso = datetime.now(timezone.utc).isoformat()
        record = AgentVisitRecord(
            visit_id=visit_id,
            agent_type=agent_type,
            user_agent=user_agent,
            target_path=target_path,
            duration_ms=duration_ms,
            status_code=status_code,
            is_agent=is_agent,
            confidence_score=confidence,
            funnel_stage=funnel_stage,
            abandonment_reasons=abandonment_reasons,
            timestamp=now_iso,
        )

        with self._lock:
            self._visits.append(record)

        return record

    def get_summary(self, max_recent: int = 50) -> AgentTrafficSummary:
        with self._lock:
            total_visits = len(self._visits)
            if total_visits == 0:
                now_iso = datetime.now(timezone.utc).isoformat()
                return AgentTrafficSummary(
                    total_visits=0,
                    agent_visits_count=0,
                    human_visits_count=0,
                    agent_traffic_ratio_pct=0.0,
                    top_agents={},
                    funnel_conversion={stage.value: 0 for stage in FunnelStage},
                    abandonment_distribution={},
                    recent_visits=[],
                    generated_at=now_iso,
                )

            agent_visits = [v for v in self._visits if v.is_agent]
            human_visits = [v for v in self._visits if not v.is_agent]

            agent_count = len(agent_visits)
            human_count = len(human_visits)
            ratio = round((agent_count / total_visits) * 100, 2)

            # Top agent breakdown
            agent_counts = Counter(v.agent_type.value for v in agent_visits)
            top_agents = dict(agent_counts.most_common(8))

            # Funnel conversion counts
            funnel_counter = Counter(v.funnel_stage.value for v in agent_visits)
            funnel_conversion = {
                FunnelStage.DISCOVERED.value: funnel_counter.get(FunnelStage.DISCOVERED.value, 0),
                FunnelStage.CONTEXT_ABSORBED.value: funnel_counter.get(FunnelStage.CONTEXT_ABSORBED.value, 0),
                FunnelStage.SANDBOX_PROBED.value: funnel_counter.get(FunnelStage.SANDBOX_PROBED.value, 0),
                FunnelStage.ADOPTED.value: funnel_counter.get(FunnelStage.ADOPTED.value, 0),
            }

            # Abandonment distribution
            abandonment_counter: Counter[str] = Counter()
            for v in agent_visits:
                for r in v.abandonment_reasons:
                    if r != AbandonmentReason.NONE:
                        abandonment_counter[r.value] += 1
            abandonment_distribution = dict(abandonment_counter.most_common(10))

            recent = self._visits[-max_recent:]
            now_iso = datetime.now(timezone.utc).isoformat()

            return AgentTrafficSummary(
                total_visits=total_visits,
                agent_visits_count=agent_count,
                human_visits_count=human_count,
                agent_traffic_ratio_pct=ratio,
                top_agents=top_agents,
                funnel_conversion=funnel_conversion,
                abandonment_distribution=abandonment_distribution,
                recent_visits=list(reversed(recent)),
                generated_at=now_iso,
            )
