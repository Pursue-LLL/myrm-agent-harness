"""Unit tests for Workspace Project Instruction Auto-Ingestor and Hierarchical Merger."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.agent.context_management.instructions import (
    ProjectInstructionConfig,
    WorkspaceProjectInstructionAutoIngestor,
)


def test_ingest_workspace_detects_agents_md_and_cursorrules(tmp_path: Path) -> None:
    # Setup mock workspace files
    agents_file = tmp_path / "AGENTS.md"
    agents_file.write_text("# Project Architecture\n- Use Python 3.13\n- Follow PEP 8\n", encoding="utf-8")

    cursorrules_file = tmp_path / ".cursorrules"
    cursorrules_file.write_text("# Cursor Rules\n- Prefer concise functions\n", encoding="utf-8")

    result = WorkspaceProjectInstructionAutoIngestor.ingest_workspace(tmp_path)

    assert result.has_active_instructions is True
    assert "AGENTS.md" in result.active_files
    assert ".cursorrules" in result.active_files
    assert len(result.discovered_files) == 2
    assert result.total_chars > 0
    assert "📄 已加载项目规范" in result.badge_label
    assert "<workspace_project_instructions" in result.formatted_prompt_block
    assert "Use Python 3.13" in result.formatted_prompt_block
    assert "Prefer concise functions" in result.formatted_prompt_block


def test_sanitize_and_zero_width_stripping(tmp_path: Path) -> None:
    dirty_text = "Standard header\u200b with \u200chidden \ufeffunicodes\n\n\n\nNext section."
    myrm_file = tmp_path / "MYRM.md"
    myrm_file.write_text(dirty_text, encoding="utf-8")

    result = WorkspaceProjectInstructionAutoIngestor.ingest_workspace(tmp_path)

    assert result.has_active_instructions is True
    file_record = result.discovered_files[0]
    assert "\u200b" not in file_record.content
    assert "\u200c" not in file_record.content
    assert "\ufeff" not in file_record.content
    assert "\n\n\n\n" not in file_record.content
    assert "Standard header with hidden unicodes" in file_record.content


def test_file_and_total_budget_truncation(tmp_path: Path) -> None:
    long_content = "X" * 500
    agents_file = tmp_path / "AGENTS.md"
    agents_file.write_text(long_content, encoding="utf-8")

    cfg = ProjectInstructionConfig(max_file_chars=100, max_total_chars=150)
    result = WorkspaceProjectInstructionAutoIngestor.ingest_workspace(tmp_path, config=cfg)

    assert result.has_active_instructions is True
    assert "[... truncated by project instruction budget]" in result.discovered_files[0].content


def test_empty_or_nonexistent_workspace(tmp_path: Path) -> None:
    # 1. Empty workspace directory
    empty_res = WorkspaceProjectInstructionAutoIngestor.ingest_workspace(tmp_path)
    assert empty_res.has_active_instructions is False
    assert "未检测到项目规范文件" in empty_res.badge_label
    assert empty_res.formatted_prompt_block == ""

    # 2. Non-existent path
    fake_path = tmp_path / "non_existent_subdir"
    bad_res = WorkspaceProjectInstructionAutoIngestor.ingest_workspace(fake_path)
    assert bad_res.has_active_instructions is False
    assert "无效的工作空间路径" in bad_res.badge_label


def test_merge_hierarchical_instructions_priority_ordering() -> None:
    merged = WorkspaceProjectInstructionAutoIngestor.merge_hierarchical_instructions(
        user_global="Global rule: Always reply in Chinese",
        agent_profile="Persona: Senior Principal Architect",
        project_instructions="<workspace_project_instructions>AGENTS.md</workspace_project_instructions>",
        turn_prompt="Task: Refactor module A",
    )

    assert '<user_global_preferences priority="10">' in merged
    assert '<agent_profile_persona priority="20">' in merged
    assert "<workspace_project_instructions>AGENTS.md</workspace_project_instructions>" in merged
    assert '<current_turn_task priority="40">' in merged

    # Verify linear order: USER < PROFILE < PROJECT < TURN
    idx_user = merged.index('priority="10"')
    idx_prof = merged.index('priority="20"')
    idx_proj = merged.index("<workspace_project_instructions>")
    idx_turn = merged.index('priority="40"')

    assert idx_user < idx_prof < idx_proj < idx_turn
