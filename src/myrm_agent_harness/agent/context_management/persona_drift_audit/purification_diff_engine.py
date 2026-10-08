# [INPUT] FileDriftAuditResult, ReconciliationDiffPlan, PurificationExecutionResult from .drift_types
# [OUTPUT] PurificationDiffEngine
# [POS] Read-only diff generator and human-confirmed purification executor enforcing "Read only until my yes"

"""Read-only diff generator and human-confirmed purification executor."""

from __future__ import annotations

from pathlib import Path

from .drift_types import (
    FileDriftAuditResult,
    PurificationExecutionResult,
    ReconciliationDiffPlan,
)


class PurificationDiffEngine:
    """Enforces the 'Read only until my yes' gate: strictly read-only diffs until explicit confirmation."""

    @classmethod
    def generate_diff_plan(
        cls,
        audit_result: FileDriftAuditResult,
        original_content: str,
    ) -> ReconciliationDiffPlan:
        """Construct a proposed red/green line-level diff plan without mutating any files on disk."""
        lines = original_content.splitlines(keepends=True)
        flagged_line_nums = {f.line_number for f in audit_result.flagged_lines}

        purified_lines: list[str] = []
        removed_line_nums: list[int] = []

        for idx, line in enumerate(lines, start=1):
            if idx in flagged_line_nums:
                removed_line_nums.append(idx)
            else:
                purified_lines.append(line)

        purified_content = "".join(purified_lines)
        removed_chars = sum(len(lines[idx - 1]) for idx in removed_line_nums)
        net_tokens_saved = max(0, removed_chars // 4)

        return ReconciliationDiffPlan(
            file_path=audit_result.file_path,
            file_kind=audit_result.file_kind,
            original_content=original_content,
            purified_content=purified_content,
            removed_line_numbers=removed_line_nums,
            modified_line_numbers={},
            net_tokens_saved=net_tokens_saved,
            requires_confirmation=True,
        )

    @classmethod
    def apply_purification(
        cls,
        diff_plan: ReconciliationDiffPlan,
        user_confirmed: bool,
        create_backup: bool = True,
    ) -> PurificationExecutionResult:
        """Atomically apply the purification plan to disk only if explicit user consent is granted."""
        # 1. Enforce 'Read only until my yes' inviolable red line
        if not user_confirmed:
            return PurificationExecutionResult(
                file_path=diff_plan.file_path,
                applied=False,
                backup_path=None,
                lines_removed=0,
                tokens_saved=0,
                message="Purification rejected: 'Read only until my yes' policy blocked unconfirmed write.",
            )

        target_path = Path(diff_plan.file_path)
        backup_path_str: str | None = None

        # 2. Safe backup before modification
        if create_backup and target_path.exists():
            backup_file = target_path.with_suffix(target_path.suffix + ".bak")
            backup_file.write_text(diff_plan.original_content, encoding="utf-8")
            backup_path_str = str(backup_file)

        # 3. Atomic file overwrite
        tmp_file = target_path.with_suffix(target_path.suffix + ".tmp")
        tmp_file.write_text(diff_plan.purified_content, encoding="utf-8")
        tmp_file.replace(target_path)

        return PurificationExecutionResult(
            file_path=str(target_path),
            applied=True,
            backup_path=backup_path_str,
            lines_removed=len(diff_plan.removed_line_numbers),
            tokens_saved=diff_plan.net_tokens_saved,
            message=(
                f"Successfully purified '{target_path.name}': removed {len(diff_plan.removed_line_numbers)} lines, "
                f"saving estimated {diff_plan.net_tokens_saved} tokens."
            ),
        )
