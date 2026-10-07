"""Bi-directional synchronizer between agent in-memory work notes and the workspace WORK_NOTES.md / PROGRESS.md files.

[INPUT]
- agent.artifacts.work_notes_syncer_types::HumanInterventionDiff, ProgressStep, StepExecutionStatus,
  SyncDirection, SyncResult, WorkNotesSnapshot (POS: Types and models for workspace work notes and progress
  file synchronization.)

[OUTPUT]
- WorkspaceWorkNotesSyncer: Bi-directional synchronizer between agent in-memory notes and workspace markdown
  files.

[POS]
Bi-directional synchronizer between agent in-memory work notes and the workspace WORK_NOTES.md / PROGRESS.md
files.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from myrm_agent_harness.agent.artifacts.work_notes_syncer_types import (
    HumanInterventionDiff,
    ProgressStep,
    StepExecutionStatus,
    SyncDirection,
    SyncResult,
    WorkNotesSnapshot,
)


class WorkspaceWorkNotesSyncer:
    """Bi-directional synchronizer between agent in-memory notes and workspace markdown files."""

    def __init__(self, workspace_root: Path | str, agent_subdir: str = ".agent") -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.agent_dir = self.workspace_root / agent_subdir
        self.notes_file_path = self.agent_dir / "WORK_NOTES.md"
        self.progress_file_path = self.agent_dir / "PROGRESS.md"

    def compute_composite_hash(self) -> str:
        """Compute composite SHA-256 hash of existing WORK_NOTES.md and PROGRESS.md files."""
        hasher = hashlib.sha256()
        for path in (self.notes_file_path, self.progress_file_path):
            if path.exists():
                hasher.update(path.read_bytes())
            else:
                hasher.update(b"__NOT_EXISTS__")
        return hasher.hexdigest()

    def check_workspace_modification(self, last_known_hash: str | None) -> bool:
        """Check whether files in workspace have been modified externally by human."""
        if not last_known_hash:
            return self.notes_file_path.exists() or self.progress_file_path.exists()
        current_hash = self.compute_composite_hash()
        return current_hash != last_known_hash

    def sync_to_workspace(self, snapshot: WorkNotesSnapshot) -> SyncResult:
        """Render snapshot to WORK_NOTES.md and PROGRESS.md and atomically persist."""
        self.agent_dir.mkdir(parents=True, exist_ok=True)
        notes_md = self._render_work_notes_md(snapshot)
        progress_md = self._render_progress_md(snapshot)

        self._atomic_write(self.notes_file_path, notes_md)
        self._atomic_write(self.progress_file_path, progress_md)

        composite_hash = self.compute_composite_hash()
        updated_snapshot = snapshot.model_copy(
            update={
                "last_synced_hash": composite_hash,
                "updated_at_iso": datetime.now(UTC).isoformat(),
            }
        )
        return SyncResult(
            direction=SyncDirection.AGENT_TO_WORKSPACE,
            success=True,
            snapshot=updated_snapshot,
            intervention_diff=None,
            message="Successfully persisted work notes and progress to workspace.",
        )

    def sync_from_workspace(self, current_snapshot: WorkNotesSnapshot | None = None) -> SyncResult:
        """Parse workspace markdown files and merge any external human edits into agent memory."""
        if not self.notes_file_path.exists() and not self.progress_file_path.exists():
            fallback = current_snapshot or WorkNotesSnapshot(goal="Default task goal")
            return SyncResult(
                direction=SyncDirection.IN_SYNC,
                success=True,
                snapshot=fallback,
                intervention_diff=None,
                message="No workspace notes found. Retained existing snapshot.",
            )

        parsed_goal, parsed_findings, parsed_disqualified, parsed_todos = self._parse_work_notes()
        parsed_steps = self._parse_progress_steps()

        # Build baseline if None
        base_goal = current_snapshot.goal if current_snapshot else parsed_goal
        base_steps = current_snapshot.steps if current_snapshot else parsed_steps
        base_findings = current_snapshot.key_findings if current_snapshot else parsed_findings
        base_todos = current_snapshot.todos if current_snapshot else parsed_todos

        # Detect human interventions
        steps_completed: list[int] = []
        for p_step in parsed_steps:
            matching_base = next((b for b in base_steps if b.step_index == p_step.step_index), None)
            if (
                matching_base
                and matching_base.status != StepExecutionStatus.COMPLETED
                and p_step.status == StepExecutionStatus.COMPLETED
            ):
                steps_completed.append(p_step.step_index)

        new_todos = [t for t in parsed_todos if t not in base_todos]
        new_findings = [f for f in parsed_findings if f not in base_findings]
        goal_changed = parsed_goal != base_goal if parsed_goal else False

        diff_detected = bool(steps_completed or new_todos or new_findings or goal_changed)
        intervention = HumanInterventionDiff(
            modified=diff_detected,
            modified_files=["WORK_NOTES.md", "PROGRESS.md"] if diff_detected else [],
            updated_goal=parsed_goal if goal_changed else None,
            steps_completed_by_human=steps_completed,
            new_todos_added=new_todos,
            new_findings_added=new_findings,
        )

        merged_snapshot = WorkNotesSnapshot(
            goal=parsed_goal or base_goal,
            current_step_index=current_snapshot.current_step_index if current_snapshot else 0,
            steps=parsed_steps if parsed_steps else base_steps,
            key_findings=list(dict.fromkeys(parsed_findings + base_findings)),
            disqualified_approaches=list(
                dict.fromkeys(
                    parsed_disqualified + (current_snapshot.disqualified_approaches if current_snapshot else [])
                )
            ),
            todos=parsed_todos if parsed_todos else base_todos,
            last_synced_hash=self.compute_composite_hash(),
            updated_at_iso=datetime.now(UTC).isoformat(),
        )

        return SyncResult(
            direction=SyncDirection.WORKSPACE_TO_AGENT,
            success=True,
            snapshot=merged_snapshot,
            intervention_diff=intervention if diff_detected else None,
            message="Merged external workspace edits into agent notes successfully."
            if diff_detected
            else "Workspace files in sync.",
        )

    def hydrate_initial_snapshot(self, fallback_goal: str = "") -> WorkNotesSnapshot:
        """Hydrate or initialize snapshot when starting session in existing workspace."""
        if self.notes_file_path.exists() or self.progress_file_path.exists():
            res = self.sync_from_workspace(None)
            return res.snapshot

        init_snapshot = WorkNotesSnapshot(
            goal=fallback_goal or "Initialize project goals",
            current_step_index=0,
            steps=[],
            key_findings=[],
            disqualified_approaches=[],
            todos=[],
        )
        self.sync_to_workspace(init_snapshot)
        return init_snapshot

    def _render_work_notes_md(self, s: WorkNotesSnapshot) -> str:
        lines = [
            f"# 🎯 任务目标与上下文 (Mission Goal)\n\n{s.goal.strip()}\n",
            "## 🔍 关键技术发现与结论 (Key Findings)\n",
        ]
        if s.key_findings:
            for item in s.key_findings:
                lines.append(f"- {item.strip()}")
        else:
            lines.append("- (尚无关键技术结论)")

        lines.append("\n## ⛔ 避坑禁忌与被否决方案 (Disqualified Approaches)\n")
        if s.disqualified_approaches:
            for item in s.disqualified_approaches:
                lines.append(f"- {item.strip()}")
        else:
            lines.append("- (暂无被否决方案)")

        lines.append("\n## 📝 待办清单与交接备忘 (Remaining Todos)\n")
        if s.todos:
            for item in s.todos:
                lines.append(f"- [ ] {item.strip()}")
        else:
            lines.append("- (暂无剩余待办)")
        lines.append("")
        return "\n".join(lines)

    def _render_progress_md(self, s: WorkNotesSnapshot) -> str:
        lines = [
            "# 📊 任务进度计划 (Progress Tracker)\n",
            f"> 当前执行步骤编号: #{s.current_step_index}\n",
        ]
        if not s.steps:
            lines.append("- [ ] 尚未配置步骤计划")
            return "\n".join(lines)

        for step in s.steps:
            if step.status == StepExecutionStatus.COMPLETED:
                box = "[x]"
                suffix = " (✅ 已完成)"
            elif step.status == StepExecutionStatus.IN_PROGRESS:
                box = "[/]"
                suffix = " (⏳ 进行中)"
            elif step.status == StepExecutionStatus.BLOCKED:
                box = "[!]"
                suffix = " (⛔ 受阻)"
            elif step.status == StepExecutionStatus.SKIPPED:
                box = "[-]"
                suffix = " (⏩ 跳过)"
            else:
                box = "[ ]"
                suffix = ""
            lines.append(f"- {box} 步骤 {step.step_index}: {step.description.strip()}{suffix}")
        lines.append("")
        return "\n".join(lines)

    def _parse_work_notes(self) -> tuple[str, list[str], list[str], list[str]]:
        if not self.notes_file_path.exists():
            return "", [], [], []
        text = self.notes_file_path.read_text(encoding="utf-8")
        sections = re.split(r"\n#+\s*", text)
        goal = ""
        findings: list[str] = []
        disqualified: list[str] = []
        todos: list[str] = []

        for sec in sections:
            sec_clean = sec.strip()
            if not sec_clean:
                continue
            first_line, *rest = sec_clean.split("\n", 1)
            body = rest[0].strip() if rest else ""

            if any(k in first_line for k in ("任务目标", "Mission Goal")):
                goal = body
            elif any(k in first_line for k in ("关键技术发现", "Key Findings")):
                findings.extend(self._extract_bullet_items(body))
            elif any(k in first_line for k in ("避坑禁忌", "被否决方案", "Disqualified")):
                disqualified.extend(self._extract_bullet_items(body))
            elif any(k in first_line for k in ("待办清单", "Todos")):
                todos.extend(self._extract_bullet_items(body))

        return goal, findings, disqualified, todos

    def _parse_progress_steps(self) -> list[ProgressStep]:
        if not self.progress_file_path.exists():
            return []
        text = self.progress_file_path.read_text(encoding="utf-8")
        step_pattern = re.compile(r"^-\s*\[([ xX/!-])\]\s*(?:步骤\s*(\d+)[:：]\s*)?(.*)$")
        steps: list[ProgressStep] = []

        for line in text.splitlines():
            line_str = line.strip()
            m = step_pattern.match(line_str)
            if m:
                mark, raw_idx, desc = m.groups()
                idx = int(raw_idx) if raw_idx else len(steps)
                clean_desc = re.sub(r"\s*\((?:✅|⏳|⛔|⏩)[^)]*\)", "", desc).strip()
                status = StepExecutionStatus.PENDING
                if mark in ("x", "X"):
                    status = StepExecutionStatus.COMPLETED
                elif mark == "/":
                    status = StepExecutionStatus.IN_PROGRESS
                elif mark == "!":
                    status = StepExecutionStatus.BLOCKED
                elif mark == "-":
                    status = StepExecutionStatus.SKIPPED

                steps.append(
                    ProgressStep(
                        step_index=idx,
                        description=clean_desc,
                        status=status,
                    )
                )
        return steps

    @staticmethod
    def _extract_bullet_items(body: str) -> list[str]:
        items: list[str] = []
        for line in body.splitlines():
            line_str = line.strip()
            line_str = re.sub(r"^-\s*(?:\[[ xX/!-]\]\s*)?", "", line_str).strip()
            if line_str and not line_str.startswith("(") and not line_str.endswith(")"):
                items.append(line_str)
        return items

    @staticmethod
    def _atomic_write(target_path: Path, content: str) -> None:
        temp_path = target_path.with_suffix(".tmp")
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(target_path)
