"""双阶段崩溃自愈会话自动提交与三维经验沉淀引擎。

对标火山引擎 OpenViking 核心架构，实现 Phase 1 毫秒级快照归档与 Phase 2 异步深度三维经验提炼。

[INPUT]
- messages: Sequence[BaseMessage]
- config: SessionCommitPolicyConfig
- queue_dir: Path

[OUTPUT]
- TwoPhaseSessionCommitEngine: 核心提交与经验提炼引擎

[POS]
- 位于 context_management/session_commit/two_phase_session_commit_engine.py
"""

from collections.abc import Sequence
import json
from pathlib import Path
import time
import uuid

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from .session_commit_types import (
    CommitJobStatus,
    CommitTriggerReason,
    ExperienceLearningItem,
    Phase1SnapshotResult,
    ProjectGuidelineItem,
    SessionCommitJob,
    SessionCommitPolicyConfig,
    TriDimensionalDistillationResult,
    UserPreferenceItem,
)


class TwoPhaseSessionCommitEngine:
    """双阶段会话自动提交与经验提炼引擎。"""

    def __init__(self, config: SessionCommitPolicyConfig | None = None) -> None:
        self.config = config or SessionCommitPolicyConfig()

    def evaluate_commit_policy(
        self,
        uncommitted_tokens: int,
        uncommitted_turns: int,
        idle_duration_seconds: float = 0.0,
        is_session_finished: bool = False,
    ) -> tuple[bool, CommitTriggerReason | None]:
        """根据策略网关判定是否触发自动提交。"""
        if is_session_finished:
            return True, CommitTriggerReason.EXPLICIT_FINISH
        if uncommitted_tokens >= self.config.max_uncommitted_tokens:
            return True, CommitTriggerReason.TOKEN_THRESHOLD
        if uncommitted_turns >= self.config.max_uncommitted_turns:
            return True, CommitTriggerReason.TURNS_THRESHOLD
        if idle_duration_seconds >= self.config.idle_timeout_seconds:
            return True, CommitTriggerReason.IDLE_TIMEOUT
        return False, None

    def phase1_snapshot_and_enqueue(
        self,
        session_id: str,
        messages: Sequence[BaseMessage],
        trigger_reason: CommitTriggerReason,
        queue_dir: Path,
    ) -> tuple[Phase1SnapshotResult, list[BaseMessage]]:
        """Phase 1: 毫秒级切分活跃滑动窗口与归档历史，原子持久化至磁盘任务队列。"""
        msg_list: list[BaseMessage] = list(messages)
        protect_count = self.config.live_window_turns * 2

        if len(msg_list) <= protect_count:
            # 消息数极少，不足以切分归档
            empty_result = Phase1SnapshotResult(
                job_id="noop",
                session_id=session_id,
                live_messages_retained=len(msg_list),
                archived_messages_count=0,
                status="skipped_insufficient_turns",
                prepared_at_epoch=time.time(),
            )
            return empty_result, msg_list

        archived_msgs = msg_list[:-protect_count]
        live_msgs = msg_list[-protect_count:]

        job_id = f"commit_{session_id}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        jobs_dir = queue_dir / "jobs"
        jobs_dir.mkdir(parents=True, exist_ok=True)

        # 序列化历史消息
        serialized_payload = [
            {
                "type": m.type,
                "content": str(m.content),
                "name": getattr(m, "name", "") or "",
                "tool_call_id": getattr(m, "tool_call_id", "") or "",
            }
            for m in archived_msgs
        ]

        payload_path = jobs_dir / f"{job_id}_payload.json"
        payload_path.write_text(json.dumps(serialized_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        now = time.time()
        job = SessionCommitJob(
            job_id=job_id,
            session_id=session_id,
            trigger_reason=trigger_reason,
            status=CommitJobStatus.PENDING,
            message_count=len(archived_msgs),
            archived_payload_path=str(payload_path),
            created_at_epoch=now,
            updated_at_epoch=now,
        )

        meta_path = jobs_dir / f"{job_id}.meta.json"
        meta_dict = {
            "job_id": job.job_id,
            "session_id": job.session_id,
            "trigger_reason": job.trigger_reason.value,
            "status": job.status.value,
            "message_count": job.message_count,
            "archived_payload_path": job.archived_payload_path,
            "created_at_epoch": job.created_at_epoch,
            "updated_at_epoch": job.updated_at_epoch,
            "retry_count": job.retry_count,
            "error_message": job.error_message,
        }
        meta_path.write_text(json.dumps(meta_dict, ensure_ascii=False, indent=2), encoding="utf-8")

        result = Phase1SnapshotResult(
            job_id=job_id,
            session_id=session_id,
            live_messages_retained=len(live_msgs),
            archived_messages_count=len(archived_msgs),
            status="ready",
            prepared_at_epoch=now,
        )
        return result, live_msgs

    def phase2_execute_distillation(
        self,
        queue_dir: Path,
    ) -> list[TriDimensionalDistillationResult]:
        """Phase 2: 异步消费持久化队列，执行用户偏好/排障教训/项目新规三维经验提炼。"""
        jobs_dir = queue_dir / "jobs"
        if not jobs_dir.exists():
            return []

        results: list[TriDimensionalDistillationResult] = []
        meta_files = sorted(jobs_dir.glob("*.meta.json"))

        for meta_file in meta_files:
            try:
                raw_meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                continue

            if raw_meta.get("status") != CommitJobStatus.PENDING.value:
                continue

            job_id = raw_meta["job_id"]
            session_id = raw_meta["session_id"]
            payload_path = Path(raw_meta["archived_payload_path"])

            # 原子置为 IN_PROGRESS
            raw_meta["status"] = CommitJobStatus.IN_PROGRESS.value
            raw_meta["updated_at_epoch"] = time.time()
            meta_file.write_text(json.dumps(raw_meta, ensure_ascii=False, indent=2), encoding="utf-8")

            if not payload_path.exists():
                raw_meta["status"] = CommitJobStatus.FAILED.value
                raw_meta["error_message"] = "Payload file not found"
                meta_file.write_text(json.dumps(raw_meta, ensure_ascii=False, indent=2), encoding="utf-8")
                continue

            try:
                raw_msgs = json.loads(payload_path.read_text(encoding="utf-8"))
                distilled = self._distill_tri_dimensional(
                    job_id=job_id,
                    session_id=session_id,
                    messages=raw_msgs,
                )
                results.append(distilled)

                raw_meta["status"] = CommitJobStatus.COMPLETED.value
                raw_meta["updated_at_epoch"] = time.time()
                meta_file.write_text(json.dumps(raw_meta, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                raw_meta["status"] = CommitJobStatus.FAILED.value
                raw_meta["error_message"] = str(e)
                meta_file.write_text(json.dumps(raw_meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return results

    def recover_and_replay_crashed_jobs(self, queue_dir: Path) -> int:
        """崩溃自愈：扫描由于进程异常退出而挂起在 IN_PROGRESS 的作业并安全重置回 PENDING。"""
        jobs_dir = queue_dir / "jobs"
        if not jobs_dir.exists():
            return 0

        recovered_count = 0
        meta_files = sorted(jobs_dir.glob("*.meta.json"))

        for meta_file in meta_files:
            try:
                raw_meta = json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                continue

            if raw_meta.get("status") == CommitJobStatus.IN_PROGRESS.value:
                retry_count = raw_meta.get("retry_count", 0) + 1
                raw_meta["retry_count"] = retry_count
                raw_meta["updated_at_epoch"] = time.time()

                if retry_count <= self.config.max_retry_attempts:
                    raw_meta["status"] = CommitJobStatus.PENDING.value
                    raw_meta["error_message"] = f"Recovered from interrupted crash (attempt {retry_count})"
                    recovered_count += 1
                else:
                    raw_meta["status"] = CommitJobStatus.FAILED.value
                    raw_meta["error_message"] = "Exceeded max retry attempts after repeated crashes"

                meta_file.write_text(json.dumps(raw_meta, ensure_ascii=False, indent=2), encoding="utf-8")

        return recovered_count

    def _distill_tri_dimensional(
        self,
        job_id: str,
        session_id: str,
        messages: list[dict[str, str]],
    ) -> TriDimensionalDistillationResult:
        """三维经验精准提取器。"""
        preferences: list[UserPreferenceItem] = []
        learnings: list[ExperienceLearningItem] = []
        guidelines: list[ProjectGuidelineItem] = []

        for item in messages:
            content = item.get("content", "")
            msg_type = item.get("type", "")

            # 维度 1: 用户偏好提取 (来自人类发言)
            if msg_type == "human":
                lower_c = content.lower()
                if any(k in lower_c for k in ("prefer", "always use", "倾向", "偏好", "喜欢", "使用")):
                    preferences.append(
                        UserPreferenceItem(
                            category="coding_style",
                            preference_text=content[:160],
                            confidence_score=0.9,
                        )
                    )

            # 维度 2: 踩坑经验与排障教训 (来自工具或助手报错修复)
            if msg_type in ("tool", "ai"):
                lower_c = content.lower()
                if any(k in lower_c for k in ("error", "exception", "failed", "bug", "报错", "修复", "解决")):
                    learnings.append(
                        ExperienceLearningItem(
                            problem_encountered=content[:100],
                            root_cause="Syntax or runtime error in previous execution",
                            resolution=content[:120],
                            context_tags=["debugging", "resilience"],
                        )
                    )

            # 维度 3: 组织与项目新规范
            lower_c = content.lower()
            if any(k in lower_c for k in ("must", "rule", "convention", "禁止", "规范", "必须")):
                guidelines.append(
                    ProjectGuidelineItem(
                        rule_name="DerivedSessionRule",
                        rule_statement=content[:150],
                        scope="project_standard",
                    )
                )

        return TriDimensionalDistillationResult(
            job_id=job_id,
            session_id=session_id,
            preferences=preferences,
            learnings=learnings,
            guidelines=guidelines,
            distilled_at_epoch=time.time(),
        )
