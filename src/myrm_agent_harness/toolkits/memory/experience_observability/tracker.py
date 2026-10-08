# [POS]: myrm_agent_harness.toolkits.memory.experience_observability.tracker
# [INPUT]: .models (ExperienceObservabilityMetric, ExperienceEffectStatus, HostAccessChannel, SessionTraceEvidence)
# [OUTPUT]: ExperienceObservabilityTracker

"""Telemetry tracker for procedure experience recall, injection, and outcome observability.

P1 delivery for Item 108 in topic_01 memory roadmap.
Supports experience item distribution stats, outcome attribution, and session traceability.

[INPUT]
- toolkits.memory.experience_observability.models::ExperienceEffectStatus, ExperienceObservabilityMetric,
  HostAccessChannel, SessionTraceEvidence (POS: Domain models for zero-refactor host lifecycle plugin and
  experience observability.)

[OUTPUT]
- ExperienceObservabilityTracker: Manages telemetry metrics for experience recalls, injections, and execution
  outcomes.

[POS]
Telemetry tracker for procedure experience recall, injection, and outcome observability.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.memory.experience_observability.models import (
    ExperienceEffectStatus,
    ExperienceObservabilityMetric,
    HostAccessChannel,
    SessionTraceEvidence,
)

logger = logging.getLogger(__name__)


def _calculate_effect_status(success_count: int, dispute_count: int) -> tuple[float, ExperienceEffectStatus]:
    """Calculate normalized success rate and categorical effect impact status."""
    total = success_count + dispute_count
    if total == 0:
        return 1.0, ExperienceEffectStatus.EFFECTIVE

    rate = round(success_count / total, 3)
    if rate >= 0.8 and success_count >= 1:
        status = ExperienceEffectStatus.EFFECTIVE
    elif rate >= 0.5:
        status = ExperienceEffectStatus.NEUTRAL
    else:
        status = ExperienceEffectStatus.ADVERSE

    return rate, status


class ExperienceObservabilityTracker:
    """Manages telemetry metrics for experience recalls, injections, and execution outcomes."""

    def __init__(
        self,
        initial_metrics: list[ExperienceObservabilityMetric] | None = None,
        initial_traces: list[SessionTraceEvidence] | None = None,
    ) -> None:
        self._metrics: dict[str, ExperienceObservabilityMetric] = {}
        self._traces: dict[str, SessionTraceEvidence] = {}

        if initial_metrics:
            for m in initial_metrics:
                self._metrics[m.entry_id] = m.model_copy(deep=True)
        else:
            self._seed_default_metrics()

        if initial_traces:
            for t in initial_traces:
                self._traces[t.session_id] = t.model_copy(deep=True)
        else:
            self._seed_default_traces()

    def _seed_default_metrics(self) -> None:
        """Seed industrial baseline observability entries matching production experiences."""
        defaults = [
            ExperienceObservabilityMetric(
                entry_id="proc_git_push_safe",
                name="SafeGitBranchPushGuard",
                source_session_id="sess_release_incident_09",
                access_channel=HostAccessChannel.PLUGIN,
                recall_count=142,
                injection_count=88,
                success_count=85,
                dispute_count=3,
                success_rate=0.966,
                effect_status=ExperienceEffectStatus.EFFECTIVE,
                last_observed_at=datetime.now(UTC).isoformat(),
            ),
            ExperienceObservabilityMetric(
                entry_id="proc_db_index_ddl",
                name="ConcurrentDbIndexMigrationGuard",
                source_session_id="sess_postgres_lock_timeout_42",
                access_channel=HostAccessChannel.MCP,
                recall_count=57,
                injection_count=34,
                success_count=32,
                dispute_count=2,
                success_rate=0.941,
                effect_status=ExperienceEffectStatus.EFFECTIVE,
                last_observed_at=datetime.now(UTC).isoformat(),
            ),
            ExperienceObservabilityMetric(
                entry_id="BA-REV-01",
                name="经营分析与PPT复盘三方法经验模板",
                source_session_id="sess_ppt_margin_analysis_88",
                access_channel=HostAccessChannel.SKILL,
                recall_count=43,
                injection_count=29,
                success_count=27,
                dispute_count=2,
                success_rate=0.931,
                effect_status=ExperienceEffectStatus.EFFECTIVE,
                last_observed_at=datetime.now(UTC).isoformat(),
            ),
            ExperienceObservabilityMetric(
                entry_id="RET-EXC-01",
                name="消费者售后换货全链路先问必查标准规程",
                source_session_id="sess_tau2_retail_exchange_01",
                access_channel=HostAccessChannel.PLUGIN,
                recall_count=98,
                injection_count=74,
                success_count=69,
                dispute_count=5,
                success_rate=0.932,
                effect_status=ExperienceEffectStatus.EFFECTIVE,
                last_observed_at=datetime.now(UTC).isoformat(),
            ),
            ExperienceObservabilityMetric(
                entry_id="ESC-GATE-01",
                name="售后与异常处置例外转人工决策门禁",
                source_session_id="sess_out_of_stock_dispute_12",
                access_channel=HostAccessChannel.PLUGIN,
                recall_count=61,
                injection_count=45,
                success_count=44,
                dispute_count=1,
                success_rate=0.978,
                effect_status=ExperienceEffectStatus.EFFECTIVE,
                last_observed_at=datetime.now(UTC).isoformat(),
            ),
        ]
        for m in defaults:
            self._metrics[m.entry_id] = m

    def _seed_default_traces(self) -> None:
        """Seed default session evidence traces."""
        defaults = [
            SessionTraceEvidence(
                session_id="sess_release_incident_09",
                title="Git生产分支误删与保护规程复盘会话",
                trajectory_summary="生产发版中工程师误执行了带强制选项的推送，后经回滚分析提炼出预检三步法。",
                key_evidence_snippets=[
                    "[Turn 4] User: 别强制推送，先检查目标远程分支保护规则！",
                    "[Turn 5] Agent: 执行 git status 确认本地工作区干净，校验上游 hash 一致性。",
                ],
                agent_role="DevOpsEngineer",
                timestamp="2026-09-18T10:00:00Z",
            ),
            SessionTraceEvidence(
                session_id="sess_postgres_lock_timeout_42",
                title="PostgreSQL千万行大表添加索引死锁排障",
                trajectory_summary="高并发库上直跑 CREATE INDEX 导致排他锁阻塞业务连接，提炼出 CONCURRENTLY 规约。",
                key_evidence_snippets=[
                    "[Turn 2] Error: lock timeout during CREATE INDEX ON orders(user_id)",
                    "[Turn 3] Agent: 切换为 CREATE INDEX CONCURRENTLY 并关闭单事务块包裹。",
                ],
                agent_role="DatabaseArchitect",
                timestamp="2026-09-20T14:30:00Z",
            ),
            SessionTraceEvidence(
                session_id="sess_ppt_margin_analysis_88",
                title="Q3季度毛利率跨表公式提取复盘会话",
                trajectory_summary="电子表格中的毛利率公式未取计算值导致大纲数据偏差，总结出公式值回查与模板验收方法。",
                key_evidence_snippets=[
                    "[Turn 6] User: 为什么汇报大纲里毛利率写的是 '=C2/B2' 字符串？",
                    "[Turn 7] Agent: 修正提取器读取 openpyxl data_only 计算结果值，完成对齐。",
                ],
                agent_role="BusinessAnalyst",
                timestamp="2026-09-22T08:15:00Z",
            ),
            SessionTraceEvidence(
                session_id="sess_tau2_retail_exchange_01",
                title="τ²-bench 消费者售后换货标准履约会话",
                trajectory_summary="顾客要求更换服装尺码，严格执行核验身份、校验签收、确认库存后办理，未产生越权违规。",
                key_evidence_snippets=[
                    "[Turn 1] User: 我的外套尺码小了想换大一号。",
                    "[Turn 2] Agent: 已核验订单并查询目标黑色L码实时库存剩余 12 件，请确认寄回旧件。",
                ],
                agent_role="CustomerServiceRepresentative",
                timestamp="2026-09-25T11:45:00Z",
            ),
            SessionTraceEvidence(
                session_id="sess_out_of_stock_dispute_12",
                title="换货目标SKU断码缺货触发转人工门禁会话",
                trajectory_summary="顾客诉求更换的款式全网断码，Agent 阻断盲目承诺发货并格式化输出人工交接工单。",
                key_evidence_snippets=[
                    "[Turn 3] Agent: 查询发现该款式已全量售罄，根据政策门禁为您接入高级人工客服专员协商补偿券。",
                ],
                agent_role="CustomerServiceRepresentative",
                timestamp="2026-09-26T16:20:00Z",
            ),
        ]
        for t in defaults:
            self._traces[t.session_id] = t

    def list_metrics(self) -> list[ExperienceObservabilityMetric]:
        """List all tracked experience metrics."""
        return list(self._metrics.values())

    def get_metric(self, entry_id: str) -> ExperienceObservabilityMetric | None:
        """Get metric details for a single experience entry."""
        return self._metrics.get(entry_id)

    def get_trace_evidence(self, session_id: str) -> SessionTraceEvidence | None:
        """Retrieve originating session trace evidence by session ID."""
        return self._traces.get(session_id)

    def record_recall(
        self,
        entry_id: str,
        channel: HostAccessChannel = HostAccessChannel.PLUGIN,
    ) -> ExperienceObservabilityMetric:
        """Record an experience recall event."""
        now_str = datetime.now(UTC).isoformat()
        metric = self._metrics.get(entry_id)
        if metric is None:
            metric = ExperienceObservabilityMetric(
                entry_id=entry_id,
                name=entry_id,
                source_session_id="unknown_source",
                access_channel=channel,
                recall_count=1,
                last_observed_at=now_str,
            )
            self._metrics[entry_id] = metric
            return metric

        metric.recall_count += 1
        metric.access_channel = channel
        metric.last_observed_at = now_str
        return metric

    def record_injection(self, entry_id: str) -> ExperienceObservabilityMetric:
        """Record an experience injection event."""
        now_str = datetime.now(UTC).isoformat()
        metric = self._metrics.get(entry_id)
        if metric is None:
            metric = ExperienceObservabilityMetric(
                entry_id=entry_id,
                name=entry_id,
                source_session_id="unknown_source",
                injection_count=1,
                last_observed_at=now_str,
            )
            self._metrics[entry_id] = metric
            return metric

        metric.injection_count += 1
        metric.last_observed_at = now_str
        return metric

    def record_effect(
        self,
        entry_id: str,
        is_success: bool,
        is_dispute: bool = False,
    ) -> ExperienceObservabilityMetric:
        """Record task execution outcome following an experience injection."""
        now_str = datetime.now(UTC).isoformat()
        metric = self._metrics.get(entry_id)
        if metric is None:
            metric = ExperienceObservabilityMetric(
                entry_id=entry_id,
                name=entry_id,
                source_session_id="unknown_source",
                last_observed_at=now_str,
            )
            self._metrics[entry_id] = metric

        if is_success:
            metric.success_count += 1
        if is_dispute:
            metric.dispute_count += 1

        rate, status = _calculate_effect_status(metric.success_count, metric.dispute_count)
        metric.success_rate = rate
        metric.effect_status = status
        metric.last_observed_at = now_str

        logger.info(
            "Updated effect for entry %s: success_rate=%.3f, status=%s",
            entry_id,
            metric.success_rate,
            metric.effect_status,
        )
        return metric
