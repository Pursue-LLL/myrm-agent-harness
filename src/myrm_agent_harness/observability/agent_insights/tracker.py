"""[INPUT] Agent operational telemetry (intent requests, skill executions, and HITL bottlenecks).
[OUTPUT] In-memory thread-safe tracker producing CustomAgentInsightsSnapshot for specific agents.
[POS] myrm_agent_harness.observability.agent_insights.tracker

Thread-safe tracker aggregating operational signals per agent_id to provide
intent clustering distributions, skill health funnels, and HITL friction analytics.
"""

from collections import Counter, defaultdict
import threading
import time

from .models import (
    AgentHitlBottleneckMetric,
    AgentIntentCluster,
    AgentSkillHealthMetric,
    CustomAgentInsightsSnapshot,
    SkillExecutionStatus,
)


class CustomAgentInsightsTracker:
    """Thread-safe tracker recording and computing operational insights per custom agent."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # agent_id -> list of (intent_category, utterance, tokens, timestamp_ms)
        self._interactions: dict[str, list[tuple[str, str, int, int]]] = defaultdict(list)
        # agent_id -> skill_name -> list of (latency_ms, status, error_reason, timestamp_ms)
        self._skills: dict[str, dict[str, list[tuple[float, SkillExecutionStatus, str, int]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        # agent_id -> list of (intercepted, wait_seconds, deliverables, tokens, timestamp_ms)
        self._hitl: dict[str, list[tuple[bool, float, int, int, int]]] = defaultdict(list)

    def record_interaction(
        self,
        agent_id: str,
        intent_category: str,
        utterance: str,
        tokens: int = 0,
        timestamp_ms: int | None = None,
    ) -> None:
        """Record an incoming query intent categorized for the agent."""
        aid = agent_id.strip()
        cat = intent_category.strip() or "general_inquiry"
        utt = utterance.strip() or "N/A"
        tok = max(0, tokens)
        ts = timestamp_ms or int(time.time() * 1000)

        with self._lock:
            self._interactions[aid].append((cat, utt, tok, ts))

    def record_skill_execution(
        self,
        agent_id: str,
        skill_name: str,
        latency_ms: float,
        status: SkillExecutionStatus | str = SkillExecutionStatus.SUCCESS,
        error_reason: str = "",
        timestamp_ms: int | None = None,
    ) -> None:
        """Record an execution timing and health outcome for a mounted skill."""
        aid = agent_id.strip()
        sname = skill_name.strip()
        safe_lat = max(0.0, float(latency_ms))
        err = error_reason.strip()
        ts = timestamp_ms or int(time.time() * 1000)

        resolved_status: SkillExecutionStatus
        if isinstance(status, SkillExecutionStatus):
            resolved_status = status
        else:
            try:
                resolved_status = SkillExecutionStatus(status.upper())
            except ValueError:
                resolved_status = SkillExecutionStatus.SUCCESS

        with self._lock:
            self._skills[aid][sname].append((safe_lat, resolved_status, err, ts))

    def record_hitl_task(
        self,
        agent_id: str,
        intercepted: bool,
        wait_seconds: float = 0.0,
        deliverables_count: int = 1,
        tokens_consumed: int = 0,
        timestamp_ms: int | None = None,
    ) -> None:
        """Record an unattended or interactive task completion with HITL friction details."""
        aid = agent_id.strip()
        wait_sec = max(0.0, float(wait_seconds))
        deliv = max(0, deliverables_count)
        tok = max(0, tokens_consumed)
        ts = timestamp_ms or int(time.time() * 1000)

        with self._lock:
            self._hitl[aid].append((intercepted, wait_sec, deliv, tok, ts))

    def get_insights_snapshot(
        self, agent_id: str, window_days: int = 7
    ) -> CustomAgentInsightsSnapshot:
        """Calculate aggregated insights within the specified time window."""
        aid = agent_id.strip()
        window_ms = max(1, window_days) * 86400 * 1000
        now_ms = int(time.time() * 1000)
        cutoff_ms = now_ms - window_ms

        with self._lock:
            # 1. Intent clusters
            raw_interactions = [
                rec for rec in self._interactions.get(aid, []) if rec[3] >= cutoff_ms
            ]
            total_interactions = len(raw_interactions)
            total_tokens = sum(rec[2] for rec in raw_interactions)

            intent_counts = Counter(rec[0] for rec in raw_interactions)
            intent_samples: dict[str, str] = {}
            for rec in raw_interactions:
                if rec[0] not in intent_samples:
                    intent_samples[rec[0]] = rec[1]

            clusters: list[AgentIntentCluster] = []
            for cat, count in intent_counts.most_common(5):
                share = round((count / total_interactions) * 100.0, 1) if total_interactions > 0 else 0.0
                clusters.append(
                    AgentIntentCluster(
                        intent_category=cat,
                        sample_utterance=intent_samples.get(cat, "N/A"),
                        request_count=count,
                        share_pct=share,
                    )
                )

            # 2. Skill funnel
            skills_dict = self._skills.get(aid, {})
            skill_metrics: list[AgentSkillHealthMetric] = []
            for sname, execs in skills_dict.items():
                filtered_execs = [e for e in execs if e[3] >= cutoff_ms]
                if not filtered_execs:
                    continue
                total_calls = len(filtered_execs)
                success_calls = sum(1 for e in filtered_execs if e[1] == SkillExecutionStatus.SUCCESS)
                succ_rate = round((success_calls / total_calls) * 100.0, 1)

                latencies = sorted(e[0] for e in filtered_execs)
                avg_lat = round(sum(latencies) / len(latencies), 1)
                p95_idx = int(len(latencies) * 0.95)
                p95_lat = round(latencies[min(p95_idx, len(latencies) - 1)], 1)

                error_reasons = [e[2] for e in filtered_execs if e[1] != SkillExecutionStatus.SUCCESS and e[2]]
                top_errors = tuple(r for r, _ in Counter(error_reasons).most_common(3))

                skill_metrics.append(
                    AgentSkillHealthMetric(
                        skill_name=sname,
                        total_calls=total_calls,
                        success_rate_pct=succ_rate,
                        avg_latency_ms=avg_lat,
                        p95_latency_ms=p95_lat,
                        top_error_reasons=top_errors,
                    )
                )

            skill_metrics.sort(key=lambda s: s.total_calls, reverse=True)

            # 3. HITL bottleneck and ROI
            hitl_tasks = [h for h in self._hitl.get(aid, []) if h[4] >= cutoff_ms]
            total_tasks = len(hitl_tasks)
            intercepted_tasks = sum(1 for h in hitl_tasks if h[0])
            hitl_rate = round((intercepted_tasks / total_tasks) * 100.0, 1) if total_tasks > 0 else 0.0

            intercepted_waits = [h[1] for h in hitl_tasks if h[0]]
            avg_wait = (
                round(sum(intercepted_waits) / len(intercepted_waits), 1)
                if intercepted_waits
                else 0.0
            )

            total_deliv = sum(h[2] for h in hitl_tasks)
            total_task_tokens = sum(h[3] for h in hitl_tasks) + total_tokens
            # Deliverables per 10,000 tokens
            token_roi = (
                round((total_deliv / (total_task_tokens / 10000.0)), 2)
                if total_task_tokens >= 1000
                else 1.0
            )

            hitl_metric = AgentHitlBottleneckMetric(
                total_tasks=total_tasks,
                hitl_intercepted_tasks=intercepted_tasks,
                hitl_interception_rate_pct=hitl_rate,
                avg_approval_wait_seconds=avg_wait,
                token_roi_ratio=token_roi,
            )

            return CustomAgentInsightsSnapshot(
                agent_id=aid,
                time_window_days=window_days,
                total_interactions=total_interactions,
                total_tokens_consumed=total_tokens,
                intent_clusters=tuple(clusters),
                skill_funnel=tuple(skill_metrics),
                hitl_metrics=hitl_metric,
            )

    def reset(self, agent_id: str | None = None) -> None:
        """Clear telemetry records for a specific agent or all agents."""
        with self._lock:
            if agent_id:
                aid = agent_id.strip()
                self._interactions.pop(aid, None)
                self._skills.pop(aid, None)
                self._hitl.pop(aid, None)
            else:
                self._interactions.clear()
                self._skills.clear()
                self._hitl.clear()


# Process-level singleton instance
_default_tracker: CustomAgentInsightsTracker | None = None
_tracker_lock = threading.Lock()


def get_default_agent_insights_tracker() -> CustomAgentInsightsTracker:
    """Obtain or initialize the global default CustomAgentInsightsTracker."""
    global _default_tracker
    if _default_tracker is None:
        with _tracker_lock:
            if _default_tracker is None:
                _default_tracker = CustomAgentInsightsTracker()
    return _default_tracker
