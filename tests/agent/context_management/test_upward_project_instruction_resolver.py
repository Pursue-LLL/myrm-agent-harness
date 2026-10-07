# ============================================================================
# Unit Tests for UpwardProjectInstructionResolverAndCrossToolZeroMigrationGate (Item 148)
# Verifies upward recursive discovery, root boundary detection, ecosystem priority
# resolution (MYRM > AGENTS > CLAUDE > CURSOR > CODEX), and legacy skills auto-mount.
# ============================================================================

from pathlib import Path

from myrm_agent_harness.agent.context_management.instructions import (
    InstructionEcosystem,
    UpwardProjectInstructionResolver,
)


def test_find_repo_root_boundary(tmp_path: Path) -> None:
    """Verifies that directory ascending halts exactly at repo root marker."""
    repo_root = tmp_path / "my_project"
    repo_root.mkdir()
    (repo_root / "pyproject.toml").write_text("[project]\nname='demo'", encoding="utf-8")

    sub_dir = repo_root / "src" / "services" / "billing" / "processors"
    sub_dir.mkdir(parents=True)

    resolver = UpwardProjectInstructionResolver()
    discovered_boundary = resolver.find_repo_root_boundary(sub_dir)
    assert discovered_boundary.resolve() == repo_root.resolve()


def test_resolve_upward_hierarchical_inheritance(tmp_path: Path) -> None:
    """Tests upward multi-level discovery from deep child directory to root."""
    repo_root = tmp_path / "enterprise_app"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()

    # Root level has legacy CLAUDE.md
    (repo_root / "CLAUDE.md").write_text("Company standard: all functions require docstrings.", encoding="utf-8")

    # Mid level has module AGENTS.md
    mid_dir = repo_root / "services" / "auth"
    mid_dir.mkdir(parents=True)
    (mid_dir / "AGENTS.md").write_text("Auth service standard: use JWT with RS256.", encoding="utf-8")

    # Deep leaf directory has no config files
    deep_leaf = mid_dir / "jwt_helpers" / "v2"
    deep_leaf.mkdir(parents=True)

    resolver = UpwardProjectInstructionResolver()
    result = resolver.resolve_upward(start_dir=deep_leaf)

    assert result.root_boundary_dir == str(repo_root.resolve())
    assert len(result.scanned_files) == 2

    # Root should come first (depth greater), child after
    assert result.scanned_files[0].ecosystem == InstructionEcosystem.CLAUDE_MD
    assert result.scanned_files[1].ecosystem == InstructionEcosystem.AGENTS_MD

    # Check generated XML markdown contains both
    markdown = result.merged_instructions_markdown
    assert '<project_instructions hierarchy="upward_resolved"' in markdown
    assert "Company standard: all functions require docstrings." in markdown
    assert "Auth service standard: use JWT with RS256." in markdown


def test_same_directory_ecosystem_precedence(tmp_path: Path) -> None:
    """Tests that within same directory, MYRM.md wins over CLAUDE.md and .cursorrules."""
    work_dir = tmp_path / "multi_tool_project"
    work_dir.mkdir()
    (work_dir / ".git").mkdir()

    # Place multiple ecosystem instruction files
    (work_dir / ".cursorrules").write_text("Cursor rules content", encoding="utf-8")
    (work_dir / "CLAUDE.md").write_text("Claude rules content", encoding="utf-8")
    (work_dir / "MYRM.md").write_text("Myrm native rules content", encoding="utf-8")

    resolver = UpwardProjectInstructionResolver()
    result = resolver.resolve_upward(start_dir=work_dir)

    assert len(result.scanned_files) == 1
    # MYRM.md should take precedence over CLAUDE.md and .cursorrules
    winner = result.scanned_files[0]
    assert winner.ecosystem == InstructionEcosystem.MYRM
    assert "Myrm native rules content" in winner.content


def test_legacy_skills_directory_auto_mounting(tmp_path: Path) -> None:
    """Verifies that foreign tool skills directories (~/.claude/skills etc) are discovered."""
    fake_home = tmp_path / "user_home"
    fake_home.mkdir()

    claude_skills = fake_home / ".claude" / "skills"
    claude_skills.mkdir(parents=True)
    (claude_skills / "git_helper.md").write_text("Git skill", encoding="utf-8")
    (claude_skills / "sql_lint.md").write_text("SQL skill", encoding="utf-8")

    fake_ws = tmp_path / "workspace"
    fake_ws.mkdir()
    agents_skills = fake_ws / ".agents" / "skills"
    agents_skills.mkdir(parents=True)
    (agents_skills / "deploy_skill.md").write_text("Deploy skill", encoding="utf-8")

    resolver = UpwardProjectInstructionResolver()
    legacy_dirs = resolver.scan_legacy_skills_directories(user_home=fake_home, workspace_dir=fake_ws)

    assert len(legacy_dirs) == 2
    claude_entry = next(d for d in legacy_dirs if d.ecosystem == InstructionEcosystem.CLAUDE_MD)
    assert claude_entry.skills_count == 2
    assert "git_helper.md" in claude_entry.manifest_names

    agents_entry = next(d for d in legacy_dirs if d.ecosystem == InstructionEcosystem.AGENTS_MD)
    assert agents_entry.skills_count == 1


def test_budget_truncation_and_zero_width_filtering(tmp_path: Path) -> None:
    """Tests budget truncation limits and zero-width hidden characters sanitization."""
    project_dir = tmp_path / "budget_proj"
    project_dir.mkdir()
    (project_dir / "pyproject.toml").write_text("[project]", encoding="utf-8")

    # Content with zero-width characters and long text
    raw_content = "Safe text\u200b with\ufeff invisible\u200c chars " + ("A" * 1500)
    (project_dir / "AGENTS.md").write_text(raw_content, encoding="utf-8")

    # Initialize with strict low budget
    resolver = UpwardProjectInstructionResolver(max_file_chars=200, total_budget_chars=150)
    result = resolver.resolve_upward(start_dir=project_dir)

    assert len(result.scanned_files) == 1
    # Check zero-width stripped
    assert "\u200b" not in result.scanned_files[0].content
    assert "\ufeff" not in result.scanned_files[0].content
    assert "[TRUNCATED_DUE_TO_BUDGET]" in result.merged_instructions_markdown
