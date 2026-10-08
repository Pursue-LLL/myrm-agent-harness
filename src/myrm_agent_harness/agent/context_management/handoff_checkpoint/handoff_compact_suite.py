"""End-to-end suite orchestrating one-click task handoff checkpoint before compaction.

[INPUT]
- agent.context_management.handoff_checkpoint.checkpoint_compiler::HandoffCheckpointCompiler (POS: Compiler
  and bidirectional markdown serializer for six-dimensional task checkpoints.)
- agent.context_management.handoff_checkpoint.checkpoint_types::HandoffCompactStage, HandoffThenCompactResult,
  TaskCheckpoint (POS: Strongly typed contracts for Handoff-then-Compact checkpoint pipeline.)

[OUTPUT]
- WorkBuddyHandoffThenCompactSuite: Industrial-grade suite implementing WorkBuddy
  handoff-checkpoint-then-compact pattern.

[POS]
End-to-end suite orchestrating one-click task handoff checkpoint before compaction.
"""

from __future__ import annotations

from typing import Callable

from .checkpoint_compiler import HandoffCheckpointCompiler
from .checkpoint_types import (
    HandoffCompactStage,
    HandoffThenCompactResult,
    TaskCheckpoint,
)


class WorkBuddyHandoffThenCompactSuite:
    """Industrial-grade suite implementing WorkBuddy handoff-checkpoint-then-compact pattern."""

    def __init__(self, compiler: HandoffCheckpointCompiler | None = None) -> None:
        """Initialize handoff-then-compact suite."""
        self._compiler: HandoffCheckpointCompiler = compiler or HandoffCheckpointCompiler()
        self._persisted_checkpoints: dict[str, TaskCheckpoint] = {}

    @property
    def compiler(self) -> HandoffCheckpointCompiler:
        """Access underlying checkpoint compiler."""
        return self._compiler

    def get_latest_checkpoint(self, session_id: str) -> TaskCheckpoint | None:
        """Retrieve the most recent handoff checkpoint for a given session."""
        return self._persisted_checkpoints.get(session_id)

    def execute_handoff_then_compact(
        self,
        session_id: str,
        ultimate_goal: str,
        completed_items: list[str] | None = None,
        important_constraints: list[str] | None = None,
        modified_files: list[str] | None = None,
        pending_issues: list[str] | None = None,
        next_actions: list[str] | None = None,
        pre_compact_tokens: int = 10_000,
        persistence_writer: Callable[[str], str] | None = None,
        compaction_runner: Callable[[int], tuple[int, bool]] | None = None,
    ) -> HandoffThenCompactResult:
        """Execute the two-phase handoff-then-compact procedure with complete safety guards.

        Step 1: Validate goal and compile six-dimensional task checkpoint.
        Step 2: Persist checkpoint to disk/workspace storage.
        Step 3: Trigger context compaction only after checkpoint is durable.
        Step 4: Record persisted checkpoint in active session registry for instant post-compact resume.
        """
        clean_goal = ultimate_goal.strip()
        if not clean_goal:
            # Defensive guard: forbid lossy compaction if no goal is anchored
            dummy_cp = self._compiler.compile_checkpoint(session_id=session_id, ultimate_goal="")
            return HandoffThenCompactResult(
                session_id=session_id,
                checkpoint=dummy_cp,
                checkpoint_uri="",
                pre_compact_tokens=pre_compact_tokens,
                post_compact_tokens=pre_compact_tokens,
                tokens_reduced=0,
                compression_ratio=0.0,
                stage=HandoffCompactStage.COMPILED,
                success=False,
                error_message="Cannot trigger compaction: ultimate_goal cannot be empty or blank.",
            )

        # 1. Compile structured checkpoint
        checkpoint: TaskCheckpoint = self._compiler.compile_checkpoint(
            session_id=session_id,
            ultimate_goal=clean_goal,
            completed_items=completed_items,
            important_constraints=important_constraints,
            modified_files=modified_files,
            pending_issues=pending_issues,
            next_actions=next_actions,
        )

        rendered_md = self._compiler.render_markdown(checkpoint)

        # 2. Persist checkpoint
        checkpoint_uri = f"workspace://checkpoints/{session_id}/TASK_CHECKPOINT.md"
        if persistence_writer is not None:
            try:
                checkpoint_uri = persistence_writer(rendered_md)
            except Exception as exc:
                return HandoffThenCompactResult(
                    session_id=session_id,
                    checkpoint=checkpoint,
                    checkpoint_uri="",
                    pre_compact_tokens=pre_compact_tokens,
                    post_compact_tokens=pre_compact_tokens,
                    tokens_reduced=0,
                    compression_ratio=0.0,
                    stage=HandoffCompactStage.COMPILED,
                    success=False,
                    error_message=f"Checkpoint persistence failed: {exc}; aborted compaction to prevent state loss.",
                )

        # 3. Compact context
        post_tokens = max(500, int(pre_compact_tokens * 0.3))
        compact_ok = True
        if compaction_runner is not None:
            try:
                post_tokens, compact_ok = compaction_runner(pre_compact_tokens)
            except Exception as exc:
                return HandoffThenCompactResult(
                    session_id=session_id,
                    checkpoint=checkpoint,
                    checkpoint_uri=checkpoint_uri,
                    pre_compact_tokens=pre_compact_tokens,
                    post_compact_tokens=pre_compact_tokens,
                    tokens_reduced=0,
                    compression_ratio=0.0,
                    stage=HandoffCompactStage.PERSISTED,
                    success=False,
                    error_message=f"Context compaction execution failed: {exc}",
                )

        if not compact_ok:
            return HandoffThenCompactResult(
                session_id=session_id,
                checkpoint=checkpoint,
                checkpoint_uri=checkpoint_uri,
                pre_compact_tokens=pre_compact_tokens,
                post_compact_tokens=pre_compact_tokens,
                tokens_reduced=0,
                compression_ratio=0.0,
                stage=HandoffCompactStage.PERSISTED,
                success=False,
                error_message="Compaction runner reported failure.",
            )

        # 4. Save checkpoint in memory registry for post-compaction re-hydration
        self._persisted_checkpoints[session_id] = checkpoint
        tokens_reduced = max(0, pre_compact_tokens - post_tokens)
        ratio = (tokens_reduced / pre_compact_tokens) if pre_compact_tokens > 0 else 0.0

        return HandoffThenCompactResult(
            session_id=session_id,
            checkpoint=checkpoint,
            checkpoint_uri=checkpoint_uri,
            pre_compact_tokens=pre_compact_tokens,
            post_compact_tokens=post_tokens,
            tokens_reduced=tokens_reduced,
            compression_ratio=round(ratio, 4),
            stage=HandoffCompactStage.COMPACTED,
            success=True,
            error_message=None,
        )

    def render_restoration_prompt(self, session_id: str) -> str | None:
        """Render prompt instruction enabling the model to resume immediately after compaction."""
        checkpoint = self._persisted_checkpoints.get(session_id)
        if checkpoint is None:
            return None

        rendered_md = self._compiler.render_markdown(checkpoint)
        return (
            "[SYSTEM NOTIFICATION: Context compacted. Read handoff checkpoint below to resume task execution]\n\n"
            f"{rendered_md}"
        )
