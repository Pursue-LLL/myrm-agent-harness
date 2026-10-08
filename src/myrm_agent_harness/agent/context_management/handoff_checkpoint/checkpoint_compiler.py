"""Compiler and bidirectional markdown serializer for six-dimensional task checkpoints.

[INPUT]
- agent.context_management.handoff_checkpoint.checkpoint_types::TaskCheckpoint (POS: Strongly typed contracts
  for Handoff-then-Compact checkpoint pipeline.)

[OUTPUT]
- HandoffCheckpointCompiler: Compiles and serializes six-dimensional task handoff checkpoints.

[POS]
Compiler and bidirectional markdown serializer for six-dimensional task checkpoints.
"""

from __future__ import annotations

import re
import time

from .checkpoint_types import TaskCheckpoint


class HandoffCheckpointCompiler:
    """Compiles and serializes six-dimensional task handoff checkpoints."""

    def compile_checkpoint(
        self,
        session_id: str,
        ultimate_goal: str,
        completed_items: list[str] | None = None,
        important_constraints: list[str] | None = None,
        modified_files: list[str] | None = None,
        pending_issues: list[str] | None = None,
        next_actions: list[str] | None = None,
        created_at_epoch_ms: int | None = None,
    ) -> TaskCheckpoint:
        """Compile structured checkpoint and automatically calculate integrity hash."""
        now_ms = created_at_epoch_ms if created_at_epoch_ms is not None else int(time.time() * 1000)
        temp_checkpoint = TaskCheckpoint(
            session_id=session_id.strip(),
            ultimate_goal=ultimate_goal.strip(),
            completed_items=list(completed_items or []),
            important_constraints=list(important_constraints or []),
            modified_files=list(modified_files or []),
            pending_issues=list(pending_issues or []),
            next_actions=list(next_actions or []),
            created_at_epoch_ms=now_ms,
            checkpoint_hash="",
        )
        digest = temp_checkpoint.calculate_digest()
        return TaskCheckpoint(
            session_id=temp_checkpoint.session_id,
            ultimate_goal=temp_checkpoint.ultimate_goal,
            completed_items=temp_checkpoint.completed_items,
            important_constraints=temp_checkpoint.important_constraints,
            modified_files=temp_checkpoint.modified_files,
            pending_issues=temp_checkpoint.pending_issues,
            next_actions=temp_checkpoint.next_actions,
            created_at_epoch_ms=temp_checkpoint.created_at_epoch_ms,
            checkpoint_hash=digest,
        )

    def render_markdown(self, checkpoint: TaskCheckpoint) -> str:
        """Render checkpoint into standard six-section markdown template."""
        lines: list[str] = [
            f"<!-- HANDOFF_TASK_CHECKPOINT:START session={checkpoint.session_id} hash={checkpoint.checkpoint_hash} -->",
            f"# TASK_CHECKPOINT: {checkpoint.session_id}",
            "",
            "## 1. 最终目标 (Ultimate Goal)",
            checkpoint.ultimate_goal if checkpoint.ultimate_goal else "_None specified_",
            "",
            "## 2. 已完成内容 (Completed Work)",
        ]
        if checkpoint.completed_items:
            lines.extend(f"- {item}" for item in checkpoint.completed_items)
        else:
            lines.append("- _None_")

        lines.extend(["", "## 3. 重要约束 (Important Constraints)"])
        if checkpoint.important_constraints:
            lines.extend(f"- {item}" for item in checkpoint.important_constraints)
        else:
            lines.append("- _None_")

        lines.extend(["", "## 4. 修改过的文件 (Modified Files)"])
        if checkpoint.modified_files:
            lines.extend(f"- `{f}`" for f in checkpoint.modified_files)
        else:
            lines.append("- _None_")

        lines.extend(["", "## 5. 待解决问题 (Pending Issues)"])
        if checkpoint.pending_issues:
            lines.extend(f"- {item}" for item in checkpoint.pending_issues)
        else:
            lines.append("- _None_")

        lines.extend(["", "## 6. 下一步动作 (Next Actions)"])
        if checkpoint.next_actions:
            lines.extend(f"- {item}" for item in checkpoint.next_actions)
        else:
            lines.append("- _None_")

        lines.extend(["", "<!-- HANDOFF_TASK_CHECKPOINT:END -->"])
        return "\n".join(lines)

    def parse_markdown(self, markdown_text: str) -> TaskCheckpoint:
        """Parse structured markdown back into strongly typed TaskCheckpoint."""
        session_match = re.search(r"<!-- HANDOFF_TASK_CHECKPOINT:START session=([^\s]+)", markdown_text)
        session_id = session_match.group(1) if session_match else "unknown_session"

        def _extract_section(heading: str) -> list[str]:
            pattern = rf"## \d+\. {re.escape(heading)}.*?\n(.*?)(?=\n## |\n<!-- HANDOFF|$)"
            match = re.search(pattern, markdown_text, re.DOTALL)
            if not match:
                return []
            content = match.group(1).strip()
            items: list[str] = []
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("- "):
                    item = stripped[2:].strip().strip("`")
                    if item not in {"_None_", "_None specified_"}:
                        items.append(item)
            return items

        goal_match = re.search(r"## 1\. 最终目标 \(Ultimate Goal\)\n(.*?)(?=\n## |$)", markdown_text, re.DOTALL)
        goal = ""
        if goal_match:
            goal_raw = goal_match.group(1).strip()
            if goal_raw != "_None specified_":
                goal = goal_raw

        completed = _extract_section("已完成内容 (Completed Work)")
        constraints = _extract_section("重要约束 (Important Constraints)")
        modified = _extract_section("修改过的文件 (Modified Files)")
        pending = _extract_section("待解决问题 (Pending Issues)")
        next_acts = _extract_section("下一步动作 (Next Actions)")

        return self.compile_checkpoint(
            session_id=session_id,
            ultimate_goal=goal,
            completed_items=completed,
            important_constraints=constraints,
            modified_files=modified,
            pending_issues=pending,
            next_actions=next_acts,
        )
