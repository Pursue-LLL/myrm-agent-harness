"""Workspace project instruction auto-ingestion and hierarchical merger engine.

[INPUT]
- os, pathlib::Path (POS: 文件系统与路径工具)
- instructions.project_instruction_types::ProjectInstructionConfig, ProjectInstructionIngestResult, DiscoveredInstructionFile, InstructionPriorityTier

[OUTPUT]
- WorkspaceProjectInstructionAutoIngestor: 工作空间根目录项目规范自动发现与分层注入器
"""

from __future__ import annotations

import re
from pathlib import Path

from .project_instruction_types import (
    DiscoveredInstructionFile,
    ProjectInstructionConfig,
    ProjectInstructionIngestResult,
)


class WorkspaceProjectInstructionAutoIngestor:
    """Auto-detects project instruction files (AGENTS.md, MYRM.md) and merges hierarchical prompts."""

    _MULTIPLE_NEWLINES_RE = re.compile(r"\n\s*\n\s*\n+")

    @classmethod
    def clean_content(cls, text: str, strip_zero_width: bool = True) -> str:
        """Sanitize raw instruction text for prefix stability and security."""
        if not text:
            return ""
        cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
        if strip_zero_width:
            cleaned = (
                cleaned.replace("\u200b", "")
                .replace("\u200c", "")
                .replace("\u200d", "")
                .replace("\ufeff", "")
            )
        cleaned = cls._MULTIPLE_NEWLINES_RE.sub("\n\n", cleaned)
        return cleaned.strip()

    @classmethod
    def ingest_workspace(
        cls,
        workspace_root: str | Path,
        config: ProjectInstructionConfig | None = None,
    ) -> ProjectInstructionIngestResult:
        """Discover and load workspace project instruction files."""
        cfg = config or ProjectInstructionConfig()
        root_path = Path(workspace_root).resolve()
        discovered_files: list[DiscoveredInstructionFile] = []
        active_filenames: list[str] = []
        total_chars = 0

        if not root_path.exists() or not root_path.is_dir():
            return ProjectInstructionIngestResult(
                workspace_root=str(root_path),
                has_active_instructions=False,
                active_files=[],
                total_chars=0,
                badge_label="⚡ 无效的工作空间路径",
                formatted_prompt_block="",
                discovered_files=[],
            )

        seen_basenames: set[str] = set()

        for candidate_rel in cfg.search_filenames:
            candidate_file = root_path / candidate_rel
            if not candidate_file.is_file():
                continue

            normalized_key = candidate_rel.lower()
            if normalized_key in seen_basenames:
                continue

            try:
                raw_text = candidate_file.read_text(encoding="utf-8", errors="replace")
                sanitized = cls.clean_content(raw_text, strip_zero_width=cfg.strip_zero_width_chars)
                if not sanitized:
                    continue

                # Single-file truncation guard
                if len(sanitized) > cfg.max_file_chars:
                    sanitized = sanitized[: cfg.max_file_chars] + "\n[... truncated by project instruction budget]"

                # Total budget guard
                remaining_budget = max(0, cfg.max_total_chars - total_chars)
                if remaining_budget <= 0:
                    break

                if len(sanitized) > remaining_budget:
                    sanitized = sanitized[:remaining_budget] + "\n[... truncated by total instruction budget]"

                char_count = len(sanitized)
                discovered_files.append(
                    DiscoveredInstructionFile(
                        path=str(candidate_file),
                        filename=candidate_rel,
                        content=sanitized,
                        char_count=char_count,
                    )
                )
                active_filenames.append(candidate_rel)
                seen_basenames.add(normalized_key)
                total_chars += char_count

            except Exception:
                continue

        if not discovered_files:
            return ProjectInstructionIngestResult(
                workspace_root=str(root_path),
                has_active_instructions=False,
                active_files=[],
                total_chars=0,
                badge_label="⚡ 未检测到项目规范文件",
                formatted_prompt_block="",
                discovered_files=[],
            )

        # Build stable XML instruction block
        block_lines = [
            f'<workspace_project_instructions root="{root_path}" active_files="{", ".join(active_filenames)}">'
        ]
        for f in discovered_files:
            block_lines.append(f"### Instruction File: {f.filename}\n{f.content}\n")
        block_lines.append("</workspace_project_instructions>")
        formatted_block = "\n".join(block_lines)

        badge = f"📄 已加载项目规范 ({', '.join(active_filenames)} · {total_chars:,} 字符)"

        return ProjectInstructionIngestResult(
            workspace_root=str(root_path),
            has_active_instructions=True,
            active_files=active_filenames,
            total_chars=total_chars,
            badge_label=badge,
            formatted_prompt_block=formatted_block,
            discovered_files=discovered_files,
        )

    @classmethod
    def merge_hierarchical_instructions(
        cls,
        user_global: str = "",
        agent_profile: str = "",
        project_instructions: str = "",
        turn_prompt: str = "",
    ) -> str:
        """Merge instructions according to strict hierarchy: USER < PROFILE < PROJECT < TURN."""
        sections: list[str] = []

        if user_global.strip():
            sections.append(
                f"<user_global_preferences priority=\"10\">\n{user_global.strip()}\n</user_global_preferences>"
            )

        if agent_profile.strip():
            sections.append(
                f"<agent_profile_persona priority=\"20\">\n{agent_profile.strip()}\n</agent_profile_persona>"
            )

        if project_instructions.strip():
            sections.append(project_instructions.strip())

        if turn_prompt.strip():
            sections.append(
                f"<current_turn_task priority=\"40\">\n{turn_prompt.strip()}\n</current_turn_task>"
            )

        return "\n\n".join(sections)
