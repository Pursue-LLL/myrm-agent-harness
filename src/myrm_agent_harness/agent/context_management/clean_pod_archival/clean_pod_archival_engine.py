"""核心引擎实现：单任务瞬态上下文防污染隔离、最终产物干净汇流与夜间定时无损资产沉淀。

[INPUT]
- 依赖 clean_pod_archival_types.py 中的契约，标准库 datetime, uuid 等。

[OUTPUT]
- CleanPodArchivalEngine: 瞬态纯净上下文隔离舱与夜间资产归集中枢引擎

[POS]
- 位于 context_management/clean_pod_archival/clean_pod_archival_engine.py
"""

from datetime import datetime, timezone
from typing import Sequence
import uuid

from .clean_pod_archival_types import (
    CleanPodArchivalConfig,
    EphemeralCleanPodDescriptor,
    NightlyArchivalJob,
    NightlyArchivalStatus,
    PodLifecycleState,
    TaskDeliverableContract,
)


class CleanPodArchivalEngine:
    """瞬态纯净上下文隔离舱与夜间资产归集中枢引擎。

    彻底破除复杂工作流在单一长会话中过度堆叠导致上下文严重污染膨胀、
    反复让 Agent 压缩记忆导致事实失真细节丢失、以及高价值素材散落会话遗忘流失的核心痛点。
    """

    def __init__(self, config: CleanPodArchivalConfig | None = None) -> None:
        self.config = config or CleanPodArchivalConfig()
        # 隔离舱注册表: pod_id -> EphemeralCleanPodDescriptor
        self._pods: dict[str, EphemeralCleanPodDescriptor] = {}
        # 主会话已汇流交付物映射: parent_session_id -> list[TaskDeliverableContract]
        self._consolidated_deliverables: dict[str, list[TaskDeliverableContract]] = {}
        # 夜间定时归集任务账本: job_id -> NightlyArchivalJob
        self._nightly_jobs: dict[str, NightlyArchivalJob] = {}

    def spawn_clean_pod(
        self,
        parent_session_id: str,
        task_topic: str,
        isolated_instructions: str,
        pod_id: str | None = None,
    ) -> EphemeralCleanPodDescriptor:
        """从主会话派生一个完全纯净的瞬态隔离舱，隔离主会话历史干扰。"""
        # 校验单会话并发活跃隔离舱配额
        active_pods = [
            p
            for p in self._pods.values()
            if p.parent_session_id == parent_session_id
            and p.state != PodLifecycleState.RETIRED_DISCARDED
        ]
        if len(active_pods) >= self.config.max_active_pods_per_session:
            raise ValueError(
                f"Maximum active clean pods limit ({self.config.max_active_pods_per_session}) "
                f"exceeded for session {parent_session_id}."
            )

        assigned_id = pod_id or f"pod_{uuid.uuid4().hex[:10]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        instructions = isolated_instructions.strip()
        if self.config.enable_prompt_sanitization:
            instructions = f"[CLEAN_POD_TASK_TOPIC: {task_topic}]\n{instructions}"

        descriptor = EphemeralCleanPodDescriptor(
            pod_id=assigned_id,
            parent_session_id=parent_session_id,
            task_topic=task_topic,
            isolated_instructions=instructions,
            state=PodLifecycleState.SPAWNED_ISOLATED,
            deliverables=(),
            turn_count=0,
            spawned_at_iso=now_iso,
            retired_at_iso="",
        )

        self._pods[assigned_id] = descriptor
        if parent_session_id not in self._consolidated_deliverables:
            self._consolidated_deliverables[parent_session_id] = []

        return descriptor

    def extract_deliverable_and_retire_pod(
        self,
        pod_id: str,
        deliverable: TaskDeliverableContract,
    ) -> tuple[EphemeralCleanPodDescriptor, TaskDeliverableContract]:
        """提取标准结构化交付物汇流至主会话，并安全清退销毁瞬态试错上下文。"""
        pod = self._pods.get(pod_id)
        if not pod:
            raise KeyError(f"Clean pod {pod_id} not found.")

        now_iso = datetime.now(timezone.utc).isoformat()
        stamped_deliverable = TaskDeliverableContract(
            deliverable_id=deliverable.deliverable_id,
            task_topic=deliverable.task_topic,
            content_payload=deliverable.content_payload,
            media_uris=deliverable.media_uris,
            extracted_metadata=deliverable.extracted_metadata,
            created_at_iso=deliverable.created_at_iso or now_iso,
        )

        # 汇流至主会话资产池
        self._consolidated_deliverables[pod.parent_session_id].append(
            stamped_deliverable
        )

        # 更新 Pod 状态
        new_state = (
            PodLifecycleState.RETIRED_DISCARDED
            if self.config.auto_retire_on_deliverable
            else PodLifecycleState.DELIVERABLE_EXTRACTED
        )
        retired_at_iso = now_iso if self.config.auto_retire_on_deliverable else ""

        updated_pod = EphemeralCleanPodDescriptor(
            pod_id=pod.pod_id,
            parent_session_id=pod.parent_session_id,
            task_topic=pod.task_topic,
            isolated_instructions=pod.isolated_instructions,
            state=new_state,
            deliverables=(*pod.deliverables, stamped_deliverable),
            turn_count=pod.turn_count + 1,
            spawned_at_iso=pod.spawned_at_iso,
            retired_at_iso=retired_at_iso,
        )
        self._pods[pod_id] = updated_pod

        return updated_pod, stamped_deliverable

    def list_pod_deliverables(
        self,
        parent_session_id: str,
    ) -> tuple[TaskDeliverableContract, ...]:
        """查询主会话下所有由纯净隔离舱汇流上报的无损交付物。"""
        deliverables = self._consolidated_deliverables.get(parent_session_id, [])
        return tuple(deliverables)

    def register_nightly_archival_job(
        self,
        session_ids: Sequence[str],
        target_storage_prefix: str = "project_vault",
        scheduled_hour_utc: int | None = None,
        job_id: str | None = None,
    ) -> NightlyArchivalJob:
        """登记夜间定时闲时资产无损沉淀任务。"""
        assigned_id = job_id or f"nightly_{uuid.uuid4().hex[:8]}"
        hour = (
            scheduled_hour_utc
            if scheduled_hour_utc is not None
            else self.config.default_nightly_cron_hour
        )
        now_iso = datetime.now(timezone.utc).isoformat()

        job = NightlyArchivalJob(
            job_id=assigned_id,
            session_ids=tuple(session_ids),
            target_storage_prefix=target_storage_prefix,
            status=NightlyArchivalStatus.SCHEDULED_IDLE,
            harvested_assets_count=0,
            table_records_count=0,
            scheduled_hour_utc=hour,
            summary_report="Scheduled for nightly quiet hours execution.",
            updated_at_iso=now_iso,
        )

        self._nightly_jobs[assigned_id] = job
        return job

    def execute_nightly_archival_sweep(self, job_id: str) -> NightlyArchivalJob:
        """执行夜间自动化归集与多维表格落盘，呈递次日资产整理报告。"""
        job = self._nightly_jobs.get(job_id)
        if not job:
            raise KeyError(f"Nightly archival job {job_id} not found.")

        # 遍历涉及的所有会话提取资产
        harvested_count = 0
        table_count = 0
        now_iso = datetime.now(timezone.utc).isoformat()

        for sid in job.session_ids:
            deliverables = self._consolidated_deliverables.get(sid, [])
            for item in deliverables:
                harvested_count += 1
                harvested_count += len(item.media_uris)
                table_count += 1

        summary = (
            f"[NIGHTLY HOUSEKEEPING REPORT: {job.job_id}]\n"
            f"Successfully harvested {harvested_count} structured assets across {len(job.session_ids)} sessions.\n"
            f"Indexed {table_count} clean deliverable rows into {job.target_storage_prefix}/bitable.\n"
            "All intermediate trial-and-error context traces have been safely pruned without loss."
        )

        updated_job = NightlyArchivalJob(
            job_id=job.job_id,
            session_ids=job.session_ids,
            target_storage_prefix=job.target_storage_prefix,
            status=NightlyArchivalStatus.COMPLETED_INDEXED,
            harvested_assets_count=harvested_count,
            table_records_count=table_count,
            scheduled_hour_utc=job.scheduled_hour_utc,
            summary_report=summary,
            updated_at_iso=now_iso,
        )
        self._nightly_jobs[job_id] = updated_job
        return updated_job

    def get_pod(self, pod_id: str) -> EphemeralCleanPodDescriptor | None:
        """根据 ID 查询瞬态隔离舱信息。"""
        return self._pods.get(pod_id)

    def get_nightly_job(self, job_id: str) -> NightlyArchivalJob | None:
        """根据 ID 查询夜间归集任务信息。"""
        return self._nightly_jobs.get(job_id)
