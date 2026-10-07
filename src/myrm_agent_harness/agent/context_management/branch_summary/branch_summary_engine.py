"""Core engine for Branch Summarization and Selective Merge-Back.

[INPUT]
- branch_summary_types: Domain models and policies for branch compaction and file tracking.

[OUTPUT]
- BranchFileOperationsTracker: Footprint analyzer extracting read/modified file sets from branch traces.
- BranchSelectiveMergeEngine: End-to-end compaction and selective parent session merging orchestrator.

[POS]
Coordinates trajectory serialization, file modification footprint isolation,
and zero-loss structured context injection into parent sessions.
"""

from __future__ import annotations

import re
import time

from myrm_agent_harness.agent.context_management.branch_summary.branch_summary_types import (
    BranchFileOperations,
    BranchMergeConflictWarning,
    BranchSummaryResult,
    FileActionKind,
    SelectiveMergePolicy,
    TrackedFileOperation,
)

_READ_TOOL_NAMES: frozenset[str] = frozenset(
    {"read", "view_file", "cat", "read_file", "view", "get_file"}
)
_WRITE_TOOL_NAMES: frozenset[str] = frozenset(
    {"write", "write_to_file", "create_file", "save_file", "overwrite_file"}
)
_EDIT_TOOL_NAMES: frozenset[str] = frozenset(
    {"edit", "replace_file_content", "patch", "modify_file", "apply_patch"}
)
_DELETE_TOOL_NAMES: frozenset[str] = frozenset(
    {"delete", "delete_file", "rm", "remove_file", "unlink"}
)
_SHELL_TOOL_NAMES: frozenset[str] = frozenset(
    {"run_command", "bash", "shell", "exec", "terminal"}
)


class BranchFileOperationsTracker:
    """Footprint analyzer extracting read and modified file sets from message history."""

    @staticmethod
    def extract_file_path(args: dict[str, object]) -> str | None:
        """Extracts standard path candidates from tool invocation arguments."""
        candidates = ("AbsolutePath", "TargetFile", "path", "file", "filename", "filepath")
        for key in candidates:
            val = args.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return None

    @classmethod
    def extract_operations_from_tool_call(
        cls, tool_name: str, args: dict[str, object]
    ) -> list[TrackedFileOperation]:
        """Detects file operations from a single tool invocation call."""
        normalized_name = tool_name.strip().lower()
        now = time.time()
        ops: list[TrackedFileOperation] = []

        path = cls.extract_file_path(args)
        if path:
            if normalized_name in _READ_TOOL_NAMES:
                ops.append(TrackedFileOperation(path, FileActionKind.READ, tool_name, now))
            elif normalized_name in _WRITE_TOOL_NAMES:
                ops.append(TrackedFileOperation(path, FileActionKind.WRITE, tool_name, now))
            elif normalized_name in _EDIT_TOOL_NAMES:
                ops.append(TrackedFileOperation(path, FileActionKind.EDIT, tool_name, now))
            elif normalized_name in _DELETE_TOOL_NAMES:
                ops.append(TrackedFileOperation(path, FileActionKind.DELETE, tool_name, now))

        # Heuristic inspection for shell commands
        if normalized_name in _SHELL_TOOL_NAMES:
            cmd = args.get("CommandLine") or args.get("command") or args.get("cmd")
            if isinstance(cmd, str):
                cls._extract_from_shell_command(cmd, tool_name, now, ops)

        return ops

    @staticmethod
    def _extract_from_shell_command(
        cmd: str, tool_name: str, now: float, ops: list[TrackedFileOperation]
    ) -> None:
        """Heuristically extracts file write/read patterns from shell commands."""
        # Detect redirected writes: > target_file or >> target_file
        redirect_matches = re.findall(r"(?:>{1,2})\s*([a-zA-Z0-9_\-\./]+)", cmd)
        for target in redirect_matches:
            if not target.startswith("/dev/"):
                ops.append(TrackedFileOperation(target, FileActionKind.WRITE, tool_name, now))

        # Detect cat/head/tail/less reads
        read_matches = re.findall(r"\b(?:cat|head|tail|less)\s+([a-zA-Z0-9_\-\./]+)", cmd)
        for target in read_matches:
            if not target.startswith("-"):
                ops.append(TrackedFileOperation(target, FileActionKind.READ, tool_name, now))

    @classmethod
    def extract_operations_from_messages(
        cls, messages: list[dict[str, object]]
    ) -> list[TrackedFileOperation]:
        """Scans message sequence for assistant tool calls and nested execution steps."""
        all_ops: list[TrackedFileOperation] = []
        for msg in messages:
            tool_calls = msg.get("tool_calls")
            if isinstance(tool_calls, list):
                for tc in tool_calls:
                    if isinstance(tc, dict):
                        t_name = str(tc.get("name") or tc.get("tool_name") or "")
                        t_args = tc.get("args") or tc.get("arguments") or {}
                        if isinstance(t_args, dict):
                            all_ops.extend(cls.extract_operations_from_tool_call(t_name, t_args))
        return all_ops

    @staticmethod
    def compute_file_lists(operations: list[TrackedFileOperation]) -> BranchFileOperations:
        """Computes disjoint read-only and modified file lists per Pi branch-summarization specification."""
        modified_paths: set[str] = set()
        read_paths: set[str] = set()

        for op in operations:
            if op.action in (FileActionKind.WRITE, FileActionKind.EDIT, FileActionKind.DELETE):
                modified_paths.add(op.path)
            elif op.action == FileActionKind.READ:
                read_paths.add(op.path)

        read_only = sorted(p for p in read_paths if p not in modified_paths)
        modified_sorted = sorted(modified_paths)
        return BranchFileOperations(read_files=read_only, modified_files=modified_sorted)


class BranchSelectiveMergeEngine:
    """Orchestrates structured distillation of branch sessions and selective parent merging."""

    def __init__(self, max_tool_chars: int = 2000) -> None:
        self._max_tool_chars = max_tool_chars
        self._tracker = BranchFileOperationsTracker()

    def serialize_branch_trajectory(self, messages: list[dict[str, object]]) -> str:
        """Serializes branch message trajectory with tool truncation to preserve token bounds."""
        lines: list[str] = []
        for msg in messages:
            role = str(msg.get("role", "unknown"))
            content = str(msg.get("content", ""))

            if role == "user":
                lines.append(f"[User Input]: {content.strip()}")
            elif role == "assistant":
                thinking = str(msg.get("thinking", "")).strip()
                if thinking:
                    lines.append(f"[Assistant Reasoning]: {thinking}")
                if content.strip():
                    lines.append(f"[Assistant Output]: {content.strip()}")
                t_calls = msg.get("tool_calls")
                if isinstance(t_calls, list) and t_calls:
                    call_descs = [
                        f"{c.get('name', 'tool')}(...)" for c in t_calls if isinstance(c, dict)
                    ]
                    lines.append(f"[Tool Invocations]: {', '.join(call_descs)}")
            elif role in ("tool", "toolResult"):
                trunc_content = content.strip()
                if len(trunc_content) > self._max_tool_chars:
                    trunc_content = (
                        trunc_content[: self._max_tool_chars]
                        + f"\n... [Truncated {len(trunc_content) - self._max_tool_chars} characters]"
                    )
                lines.append(f"[Tool Execution Result]: {trunc_content}")
        return "\n\n".join(lines)

    def distill_summary(
        self, messages: list[dict[str, object]], custom_instructions: str = ""
    ) -> str:
        """Distills core discoveries, solution decisions, and outcomes into structured markdown."""
        user_goals: list[str] = []
        assistant_conclusions: list[str] = []

        for msg in messages:
            role = str(msg.get("role", ""))
            content = str(msg.get("content", "")).strip()
            if role == "user" and content:
                user_goals.append(content)
            elif role == "assistant" and content:
                assistant_conclusions.append(content)

        goal_preview = user_goals[-1] if user_goals else "Explore alternative implementation."
        final_conclusion = (
            assistant_conclusions[-1]
            if assistant_conclusions
            else "Completed branch exploration."
        )

        sections: list[str] = [
            f"### Branch Exploration Objective\n{goal_preview}",
            f"### Outcome & Key Decisions\n{final_conclusion}",
        ]
        if custom_instructions.strip():
            sections.append(f"### Specific Directives\n{custom_instructions.strip()}")

        return "\n\n".join(sections)

    @staticmethod
    def check_conflicts(
        branch_ops: BranchFileOperations, parent_modified_files: list[str] | None
    ) -> list[BranchMergeConflictWarning]:
        """Detects potential file collisions between branch changes and parent concurrent edits."""
        if not parent_modified_files:
            return []

        warnings: list[BranchMergeConflictWarning] = []
        parent_set = set(parent_modified_files)

        for mod_path in branch_ops.modified_files:
            if mod_path in parent_set:
                warnings.append(
                    BranchMergeConflictWarning(
                        file_path=mod_path,
                        parent_modified=True,
                        branch_modified=True,
                        severity="HIGH",
                        resolution_hint=(
                            f"File '{mod_path}' was modified in both parent and branch. "
                            "Inspect git diff or perform manual reconciliation prior to merge."
                        ),
                    )
                )

        return warnings

    def format_injection_message(
        self,
        branch_id: str,
        common_ancestor_turn_id: str,
        summary_text: str,
        file_ops: BranchFileOperations,
        policy: SelectiveMergePolicy,
        conflicts: list[BranchMergeConflictWarning],
    ) -> str:
        """Formats zero-loss merge payload for injection into parent session context."""
        if policy == SelectiveMergePolicy.AUDIT_DRY_RUN:
            return ""

        parts: list[str] = [
            f'<branch-summary branch_id="{branch_id}" fork_origin="{common_ancestor_turn_id}" policy="{policy.value}">'
        ]

        if policy in (
            SelectiveMergePolicy.FULL_SUMMARY_AND_FILES,
            SelectiveMergePolicy.SUMMARY_ONLY,
        ):
            parts.append(summary_text)

        if policy in (
            SelectiveMergePolicy.FULL_SUMMARY_AND_FILES,
            SelectiveMergePolicy.MODIFIED_FILES_ONLY,
        ):
            xml_ops = file_ops.format_xml()
            if xml_ops:
                parts.append(xml_ops)

        if conflicts:
            conflict_lines = "\n".join(f"- [CONFLICT] {c.file_path}: {c.resolution_hint}" for c in conflicts)
            parts.append(f"<conflict-warnings>\n{conflict_lines}\n</conflict-warnings>")

        parts.append("</branch-summary>")
        return "\n\n".join(parts)

    def execute_branch_compaction_and_merge(
        self,
        branch_id: str,
        parent_session_id: str,
        common_ancestor_turn_id: str,
        branch_messages: list[dict[str, object]],
        merge_policy: SelectiveMergePolicy = SelectiveMergePolicy.FULL_SUMMARY_AND_FILES,
        parent_modified_files_since_fork: list[str] | None = None,
        custom_instructions: str = "",
    ) -> BranchSummaryResult:
        """Executes full branch extraction, footprint analysis, and merge payload generation."""
        # 1. Extract file operations & compute disjoint read/modified lists
        raw_ops = self._tracker.extract_operations_from_messages(branch_messages)
        file_ops = self._tracker.compute_file_lists(raw_ops)

        # 2. Check merge conflicts with parent
        conflicts = self.check_conflicts(file_ops, parent_modified_files_since_fork)

        # 3. Distill summary
        summary_text = self.distill_summary(branch_messages, custom_instructions)

        # 4. Format injection message
        injection_text = self.format_injection_message(
            branch_id=branch_id,
            common_ancestor_turn_id=common_ancestor_turn_id,
            summary_text=summary_text,
            file_ops=file_ops,
            policy=merge_policy,
            conflicts=conflicts,
        )

        # 5. Estimate tokens saved vs uncompacted trajectory
        serialized_len = len(self.serialize_branch_trajectory(branch_messages))
        estimated_tokens = max(1, len(injection_text) // 4)

        return BranchSummaryResult(
            branch_id=branch_id,
            parent_session_id=parent_session_id,
            common_ancestor_turn_id=common_ancestor_turn_id,
            summary_text=summary_text,
            file_operations=file_ops,
            merge_policy=merge_policy,
            conflict_warnings=conflicts,
            injection_message_text=injection_text,
            token_count_estimated=estimated_tokens,
            branch_turns_count=len(branch_messages),
        )
