# [INPUT]: ConflictArbitrationResult, RuleGovernanceConfig
# [OUTPUT]: MemoryFileConflictArbiter
# [POS]: agent/workspace_rules/rule_governance/memory_file_conflict_arbiter.py

"""Arbiter resolving dual-storage contradictions between memory facts and workspace rule files.

[INPUT]
- ConflictArbitrationResult: Outcome container detailing which source won and rationale.
- RuleGovernanceConfig: Settings indicating whether workspace rule files are authoritative SSOT.

[OUTPUT]
- MemoryFileConflictArbiter: Stateless decision engine adjudicating contradictions and emitting pointers.

[POS]
Conflict resolution and SSOT preservation layer in AGENTS.md lifecycle governance.
"""

from __future__ import annotations

import os
from .governance_types import ConflictArbitrationResult, RuleGovernanceConfig


class MemoryFileConflictArbiter:
    """Arbitrates disagreements between long-term memory entries and workspace rules."""

    def __init__(self, config: RuleGovernanceConfig | None = None) -> None:
        self._config = config or RuleGovernanceConfig()

    def arbitrate_conflict(
        self,
        memory_key: str,
        memory_fact: str,
        memory_mtime: float,
        rule_file_path: str,
        rule_content: str,
        file_mtime: float,
    ) -> ConflictArbitrationResult:
        """Determines authoritative source between memory and workspace file."""
        file_name = os.path.basename(rule_file_path)

        if self._config.file_ssot_authoritative:
            # File is treated as authoritative single source of truth (SSOT)
            if file_mtime >= memory_mtime:
                winner = "file"
                reason = "Workspace file is newer and acts as authoritative SSOT."
            else:
                winner = "file"
                reason = "Workspace file is authoritative SSOT; memory has newer timestamp but file governs active execution."

            alert = (
                f"⚠️ 检测到长期记忆与当前项目规则冲突：已优先遵循权威工作区规则文件《{file_name}》，"
                f"防止双重存储引发认知分裂。"
            )
        else:
            # Timestamp-based resolution fallback
            if memory_mtime > file_mtime:
                winner = "memory"
                reason = "Long-term memory timestamp is newer than workspace file."
                alert = f"⚠️ 长期记忆更新于工作区文件之后，已采用记忆版本并建议同步工作区文件《{file_name}》。"
            else:
                winner = "file"
                reason = "Workspace file timestamp is equal to or newer than memory."
                alert = f"⚠️ 工作区文件《{file_name}》更新于长期记忆之后，已采用文件版本。"

        return ConflictArbitrationResult(
            memory_key=memory_key,
            rule_file_path=rule_file_path,
            file_mtime=file_mtime,
            memory_mtime=memory_mtime,
            winner=winner,
            arbitration_reason=reason,
            alert_message=alert,
        )

    @staticmethod
    def build_rule_reference_pointer(file_path: str, content_sha256: str) -> str:
        """Constructs an unambiguous pointer reference (rule_ref@path:hash) to avoid dual-storage replication."""
        short_hash = content_sha256[:12] if len(content_sha256) >= 12 else content_sha256
        return f"rule_ref@{file_path}:{short_hash}"
