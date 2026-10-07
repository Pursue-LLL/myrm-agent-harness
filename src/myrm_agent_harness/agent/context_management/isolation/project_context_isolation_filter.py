# ============================================================================
# # ProjectContextIsolationFilter - Cross-Project Shield & Objective Recap (Item 145)
# # Enforces project-scoped session physical boundaries, strips alien file references,
# # detects ambiguous continuation triggers, and verifies one-line objective assertions.
# ============================================================================

from __future__ import annotations

import os
import re
from re import Pattern

from .project_isolation_types import (
    CrossProjectCheckResult,
    ObjectiveRecapAssertion,
    ObjectiveRecapStatus,
    ProjectBoundary,
)

_AMBIGUOUS_PATTERNS: tuple[str, ...] = (
    r"^(继续|接着|按刚才|按照刚才|接着刚才|继续刚才)",
    r"^(继续做|继续修|继续写|继续改|继续优化|继续执行)",
    r"^(continue|go on|proceed|resume)(\s+with|\s+from)?(\s+previous|\s+last)?",
    r"^(keep going|carry on)",
)

_COMPILED_AMBIGUOUS_REGEXES: list[Pattern[str]] = [
    re.compile(pat, re.IGNORECASE) for pat in _AMBIGUOUS_PATTERNS
]


class ProjectContextIsolationFilter:
    """Guards context against cross-project data bleed and asserts task alignment."""

    def __init__(self) -> None:
        pass

    def filter_cross_project_files(
        self,
        boundary: ProjectBoundary,
        candidate_paths: list[str],
    ) -> CrossProjectCheckResult:
        """Partitions candidate file paths into retained (in-boundary) and filtered (alien)."""
        retained: list[str] = []
        filtered: list[str] = []

        for path in candidate_paths:
            if boundary.is_path_within_boundary(path):
                retained.append(path)
            else:
                filtered.append(path)

        is_aligned = len(filtered) == 0
        violation = (
            f"Detected {len(filtered)} file references outside workspace '{boundary.workspace_root}'"
            if filtered
            else None
        )

        return CrossProjectCheckResult(
            is_aligned=is_aligned,
            filtered_file_paths=filtered,
            retained_file_paths=retained,
            violation_reason=violation,
        )

    def is_ambiguous_continuation_prompt(self, prompt: str) -> bool:
        """Determines if a prompt relies on implicit continuation without explicit target."""
        stripped = prompt.strip()
        if not stripped:
            return False
        return any(rgx.search(stripped) is not None for rgx in _COMPILED_AMBIGUOUS_REGEXES)

    def assert_objective_alignment(
        self,
        boundary: ProjectBoundary,
        current_cwd: str,
        prompt: str,
        current_objective: str,
        force_recap: bool = False,
    ) -> ObjectiveRecapAssertion:
        """Asserts objective and workspace alignment before prompt processing.

        Blocks execution if the current active working directory (current_cwd)
        violates the session's physical ProjectBoundary.
        """
        norm_boundary_root = os.path.abspath(boundary.workspace_root)
        norm_cwd = os.path.abspath(current_cwd)

        # 1. Physical directory mismatch detection
        if norm_cwd != norm_boundary_root and not norm_cwd.startswith(norm_boundary_root.rstrip(os.sep) + os.sep):
            warning = (
                f"🚨 跨项目安全阻断: 当前工作目录 '{norm_cwd}' 与会话绑定的项目 '{boundary.project_id}' "
                f"根路径 '{norm_boundary_root}' 不匹配！已终止执行以防上下文串线破坏代码。"
            )
            return ObjectiveRecapAssertion(
                status=ObjectiveRecapStatus.MISMATCH_INTERCEPTED,
                project_id=boundary.project_id,
                workspace_root=norm_boundary_root,
                objective_summary=current_objective,
                recap_display_badge="⛔ [跨项目串线拦截]",
                is_blocked=True,
                warning_message=warning,
            )

        # 2. Check ambiguous continuation trigger or explicit force_recap
        is_ambiguous = self.is_ambiguous_continuation_prompt(prompt)
        if is_ambiguous or force_recap:
            clean_obj = current_objective.strip() or "未指定具体目标"
            badge = f"🎯 [当前项目目标对齐] 项目: {boundary.project_id} | 根路径: {norm_boundary_root} | 目标: {clean_obj}"
            return ObjectiveRecapAssertion(
                status=ObjectiveRecapStatus.VERIFIED,
                project_id=boundary.project_id,
                workspace_root=norm_boundary_root,
                objective_summary=clean_obj,
                recap_display_badge=badge,
                is_blocked=False,
                warning_message=None,
            )

        # 3. Standard unambiguous prompt bypass
        return ObjectiveRecapAssertion(
            status=ObjectiveRecapStatus.BYPASSED,
            project_id=boundary.project_id,
            workspace_root=norm_boundary_root,
            objective_summary=current_objective,
            recap_display_badge="",
            is_blocked=False,
            warning_message=None,
        )

    def sanitize_alien_paths_in_text(
        self,
        boundary: ProjectBoundary,
        text: str,
        alien_paths: list[str],
    ) -> str:
        """Redacts alien file paths from context text to prevent model hallucination."""
        if not alien_paths:
            return text

        sanitized = text
        for alien in alien_paths:
            if alien in sanitized:
                sanitized = sanitized.replace(alien, f"[CROSS_PROJECT_REDACTED: {os.path.basename(alien)}]")
        return sanitized
