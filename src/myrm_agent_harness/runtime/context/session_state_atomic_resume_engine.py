"""Session state atomic checkpoint manager and resume protocol engine.

Coordinates step-level lifecycle checkpoints, detects crash interruptions,
performs idempotency checks for interrupted tool calls, and generates atomic resume plans.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence

from myrm_agent_harness.runtime.context.session_checkpoint_storage import (
    SessionCheckpointStorage,
)
from myrm_agent_harness.runtime.context.session_checkpoint_types import (
    AtomicResumeDecision,
    CheckpointStepStatus,
    SessionCheckpointConfig,
    SessionStepCheckpoint,
    ToolActionRecoveryKind,
    ToolExecutionSnapshot,
)

_READ_ONLY_TOOLS: tuple[str, ...] = (
    "read_file",
    "view_file",
    "list_dir",
    "web_search",
    "search_web",
    "read_url_content",
    "grep",
    "find",
)


class SessionStateAtomicResumeEngine:
    """Engine managing step-level checkpoint transitions and seamless recovery."""

    def __init__(
        self,
        storage: SessionCheckpointStorage | None = None,
        config: SessionCheckpointConfig | None = None,
    ) -> None:
        self._config = config or SessionCheckpointConfig()
        self._storage = storage or SessionCheckpointStorage(self._config)

    def start_step(
        self,
        session_id: str,
        step_index: int,
        messages_count: int,
        workspace_fingerprint: str,
    ) -> SessionStepCheckpoint:
        """Mark the beginning of an agent execution step."""
        ckpt = SessionStepCheckpoint(
            checkpoint_id=f"ckpt_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            step_index=step_index,
            status=CheckpointStepStatus.STEP_STARTED,
            workspace_fingerprint=workspace_fingerprint,
            messages_count=messages_count,
            timestamp=time.time(),
        )
        self._storage.save_checkpoint(ckpt)
        return ckpt

    def begin_tool_invocation(
        self,
        session_id: str,
        step_index: int,
        tool_name: str,
        call_id: str,
        input_args: dict[str, str],
        workspace_fingerprint: str,
        messages_count: int,
    ) -> SessionStepCheckpoint:
        """Record an in-flight tool invocation before execution dispatch."""
        is_read_only = tool_name.lower() in _READ_ONLY_TOOLS
        snapshot = ToolExecutionSnapshot(
            tool_name=tool_name,
            call_id=call_id,
            input_args=input_args,
            is_idempotent=is_read_only,
            output_preview=None,
            executed_at=time.time(),
        )
        ckpt = SessionStepCheckpoint(
            checkpoint_id=f"ckpt_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            step_index=step_index,
            status=CheckpointStepStatus.TOOL_INVOKING,
            workspace_fingerprint=workspace_fingerprint,
            messages_count=messages_count,
            pending_tool_call=snapshot,
            timestamp=time.time(),
        )
        self._storage.save_checkpoint(ckpt)
        return ckpt

    def complete_tool_invocation(
        self,
        session_id: str,
        step_index: int,
        tool_name: str,
        call_id: str,
        output_preview: str,
        workspace_fingerprint: str,
        messages_count: int,
    ) -> SessionStepCheckpoint:
        """Record the successful completion of a tool invocation."""
        is_read_only = tool_name.lower() in _READ_ONLY_TOOLS
        snapshot = ToolExecutionSnapshot(
            tool_name=tool_name,
            call_id=call_id,
            input_args={},
            is_idempotent=is_read_only,
            output_preview=output_preview[:300],
            executed_at=time.time(),
        )
        ckpt = SessionStepCheckpoint(
            checkpoint_id=f"ckpt_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            step_index=step_index,
            status=CheckpointStepStatus.TOOL_COMPLETED,
            workspace_fingerprint=workspace_fingerprint,
            messages_count=messages_count,
            pending_tool_call=snapshot,
            timestamp=time.time(),
        )
        self._storage.save_checkpoint(ckpt)
        return ckpt

    def commit_step(
        self,
        session_id: str,
        step_index: int,
        workspace_fingerprint: str,
        messages_count: int,
    ) -> SessionStepCheckpoint:
        """Seal and commit the step boundary once turn response finishes."""
        ckpt = SessionStepCheckpoint(
            checkpoint_id=f"ckpt_{uuid.uuid4().hex[:12]}",
            session_id=session_id,
            step_index=step_index,
            status=CheckpointStepStatus.STEP_COMMITTED,
            workspace_fingerprint=workspace_fingerprint,
            messages_count=messages_count,
            timestamp=time.time(),
        )
        self._storage.save_checkpoint(ckpt)
        return ckpt

    def detect_interruption(self, session_id: str) -> bool:
        """Detect whether a session was abruptly terminated before step commit."""
        latest = self._storage.get_latest_checkpoint(session_id)
        if latest is None:
            return False
        return latest.status in (
            CheckpointStepStatus.TOOL_INVOKING,
            CheckpointStepStatus.STEP_STARTED,
        )

    def evaluate_resume_decision(
        self,
        session_id: str,
        current_workspace_fingerprint: str | None = None,
    ) -> AtomicResumeDecision:
        """Evaluate latest checkpoint and compute the seamless resume strategy."""
        latest = self._storage.get_latest_checkpoint(session_id)
        if latest is None or latest.status == CheckpointStepStatus.STEP_COMMITTED:
            return AtomicResumeDecision(
                can_resume=False,
                resume_step_index=0 if latest is None else latest.step_index,
                recommended_action=ToolActionRecoveryKind.SKIP_AND_REUSE,
                prompt_instructions="",
                divergence_detected=False,
                last_checkpoint_id=latest.checkpoint_id if latest else None,
            )

        # Interrupted during tool invocation
        tool_snap = latest.pending_tool_call
        if latest.status == CheckpointStepStatus.TOOL_INVOKING and tool_snap is not None:
            is_read_only = tool_snap.tool_name.lower() in _READ_ONLY_TOOLS

            if is_read_only:
                # Read-only tools have no side effects, safe to re-execute
                instructions = (
                    f"检测到上次会话在执行只读工具 `{tool_snap.tool_name}` 时意外中断。\n"
                    f"工作区状态保持完好，已就绪从第 {latest.step_index} 步安全重新执行该工具。"
                )
                return AtomicResumeDecision(
                    can_resume=True,
                    resume_step_index=latest.step_index,
                    recommended_action=ToolActionRecoveryKind.RE_EXECUTE,
                    prompt_instructions=instructions,
                    divergence_detected=False,
                    last_checkpoint_id=latest.checkpoint_id,
                )

            # Mutating tool: compare workspace fingerprint to check if write persisted
            diverged = False
            if current_workspace_fingerprint is not None:
                diverged = current_workspace_fingerprint != latest.workspace_fingerprint

            if diverged:
                # Workspace fingerprint changed: file modifications already landed on disk
                instructions = (
                    f"检测到修改型工具 `{tool_snap.tool_name}` 在崩溃前已成功落盘写入（指纹已更新）。\n"
                    f"建议跳过重复写入以避免覆写破坏，直接复用当前产物并从第 {latest.step_index + 1} 步继续推进。"
                )
                action = ToolActionRecoveryKind.SKIP_AND_REUSE
            else:
                # Workspace fingerprint unchanged: write was interrupted before disk write
                instructions = (
                    f"检测到修改型工具 `{tool_snap.tool_name}` 尚未落盘（工作区指纹未改变）。\n"
                    f"已就绪从第 {latest.step_index} 步重新发起幂等写入。"
                )
                action = ToolActionRecoveryKind.RE_EXECUTE

            return AtomicResumeDecision(
                can_resume=True,
                resume_step_index=latest.step_index,
                recommended_action=action,
                prompt_instructions=instructions,
                divergence_detected=diverged,
                last_checkpoint_id=latest.checkpoint_id,
            )

        # Interrupted during step start before any tool invocation
        instructions = (
            f"检测到在第 {latest.step_index} 步尚未派发工具调用时意外中断。\n"
            f"已就绪从当前断点第 {latest.step_index} 步重新继续分析并推进。"
        )
        return AtomicResumeDecision(
            can_resume=True,
            resume_step_index=latest.step_index,
            recommended_action=ToolActionRecoveryKind.RE_EXECUTE,
            prompt_instructions=instructions,
            divergence_detected=False,
            last_checkpoint_id=latest.checkpoint_id,
        )

    def rewind_to_checkpoint(
        self, session_id: str, target_checkpoint_id: str
    ) -> SessionStepCheckpoint:
        """Rewind timeline back to a specific checkpoint and seal an intervention mark."""
        target = self._storage.get_checkpoint(session_id, target_checkpoint_id)
        if target is None:
            raise KeyError(
                f"Checkpoint {target_checkpoint_id} not found in session {session_id}"
            )

        rewind_ckpt = SessionStepCheckpoint(
            checkpoint_id=f"ckpt_rewind_{uuid.uuid4().hex[:8]}",
            session_id=session_id,
            step_index=target.step_index,
            status=CheckpointStepStatus.STEP_COMMITTED,
            workspace_fingerprint=target.workspace_fingerprint,
            messages_count=target.messages_count,
            timestamp=time.time(),
            metadata={"rewound_from": target_checkpoint_id},
        )
        self._storage.save_checkpoint(rewind_ckpt)
        return rewind_ckpt

    def list_history_checkpoints(
        self, session_id: str
    ) -> Sequence[SessionStepCheckpoint]:
        """Fetch timeline of checkpoints recorded for a session."""
        return self._storage.list_checkpoints(session_id)
