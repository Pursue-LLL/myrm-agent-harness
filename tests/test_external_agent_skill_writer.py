# [POS] tests/test_external_agent_skill_writer.py
# [INPUT] myrm_agent_harness.toolkits.memory.external_bridge, pytest, tmp_path
# [OUTPUT] TestExternalAgentSkillWriterSuite

"""Unit tests for external agent memory bridge and safe skill writer."""

from __future__ import annotations

from pathlib import Path

from myrm_agent_harness.toolkits.memory.external_bridge import (
    END_MARKER,
    START_MARKER,
    ExternalAgentSkillWriter,
    ExternalAgentTargetRegistry,
    ExternalAgentType,
    MemoryPluginConflictDetector,
    SkillBridgeAction,
    SkillInstallConfig,
)


def test_target_registry_contains_all_agents() -> None:
    """Verify registry resolves all 5 default external agent targets."""
    registry = ExternalAgentTargetRegistry()
    supported = registry.list_supported_agents()
    expected = [
        ExternalAgentType.CURSOR,
        ExternalAgentType.CLAUDE_CODE,
        ExternalAgentType.CODEX,
        ExternalAgentType.HERMES,
        ExternalAgentType.OPENCLAW,
    ]
    for agent in expected:
        assert agent in supported
        target = registry.get(agent)
        assert target.agent_type == agent


def test_skill_writer_install_creates_new_file(tmp_path: Path) -> None:
    """Verify installation creates a fresh file with delimited markers."""
    writer = ExternalAgentSkillWriter()
    target_file = tmp_path / "CLAUDE.md"
    config = SkillInstallConfig(
        agent_type=ExternalAgentType.CLAUDE_CODE,
        custom_target_path=target_file,
        api_base_url="http://127.0.0.1:9099",
    )

    result = writer.install(config)
    assert result.success is True
    assert result.action == SkillBridgeAction.CREATED
    assert target_file.exists()

    content = target_file.read_text(encoding="utf-8")
    assert START_MARKER in content
    assert END_MARKER in content
    assert "http://127.0.0.1:9099/api/memory/external/query" in content
    assert "http://127.0.0.1:9099/api/memory/external/contribute" in content


def test_skill_writer_idempotent_install(tmp_path: Path) -> None:
    """Verify repeated install on identical configuration returns UNCHANGED."""
    writer = ExternalAgentSkillWriter()
    target_file = tmp_path / ".cursorrules"
    config = SkillInstallConfig(
        agent_type=ExternalAgentType.CURSOR,
        custom_target_path=target_file,
    )

    res1 = writer.install(config)
    assert res1.action == SkillBridgeAction.CREATED

    res2 = writer.install(config)
    assert res2.action == SkillBridgeAction.UNCHANGED
    assert res2.success is True


def test_skill_writer_preserves_existing_user_instructions(tmp_path: Path) -> None:
    """Verify user pre-existing configuration is strictly untouched."""
    writer = ExternalAgentSkillWriter()
    target_file = tmp_path / "CODEX.md"
    user_header = "# Project Instructions\nAlways use strictly typed dataclasses."
    target_file.write_text(user_header, encoding="utf-8")

    config = SkillInstallConfig(
        agent_type=ExternalAgentType.CODEX,
        custom_target_path=target_file,
    )

    res = writer.install(config)
    assert res.action == SkillBridgeAction.UPDATED
    assert res.success is True

    content = target_file.read_text(encoding="utf-8")
    assert content.startswith(user_header)
    assert START_MARKER in content
    assert END_MARKER in content


def test_skill_writer_update_only_alters_marker_section(tmp_path: Path) -> None:
    """Verify updating only re-renders contents inside delimiters."""
    writer = ExternalAgentSkillWriter()
    target_file = tmp_path / "HERMES.md"
    user_rule = "# Custom Rules\nDo not delete logs."
    target_file.write_text(user_rule, encoding="utf-8")

    cfg1 = SkillInstallConfig(
        agent_type=ExternalAgentType.HERMES,
        custom_target_path=target_file,
        api_base_url="http://127.0.0.1:8000",
    )
    writer.install(cfg1)

    cfg2 = SkillInstallConfig(
        agent_type=ExternalAgentType.HERMES,
        custom_target_path=target_file,
        api_base_url="http://10.0.0.5:9000",
    )
    res = writer.install(cfg2)
    assert res.action == SkillBridgeAction.UPDATED

    updated = target_file.read_text(encoding="utf-8")
    assert user_rule in updated
    assert "http://10.0.0.5:9000" in updated
    assert "http://127.0.0.1:8000" not in updated


def test_skill_writer_uninstall_cleanly_strips_markers(tmp_path: Path) -> None:
    """Verify uninstall strips markers without corrupting remaining file content."""
    writer = ExternalAgentSkillWriter()
    target_file = tmp_path / "OPENCLAW.md"
    user_custom = "# Preserve Me\nCustom pipeline step."
    target_file.write_text(user_custom, encoding="utf-8")

    cfg = SkillInstallConfig(
        agent_type=ExternalAgentType.OPENCLAW,
        custom_target_path=target_file,
    )
    writer.install(cfg)

    # Uninstall
    unres = writer.uninstall(cfg)
    assert unres.success is True
    assert unres.removed is True
    assert unres.file_deleted is False

    final_content = target_file.read_text(encoding="utf-8").strip()
    assert final_content == user_custom
    assert START_MARKER not in final_content
    assert END_MARKER not in final_content


def test_skill_writer_uninstall_deletes_empty_file(tmp_path: Path) -> None:
    """Verify uninstall deletes file if it only contained bridge markers."""
    writer = ExternalAgentSkillWriter()
    target_file = tmp_path / "CLAUDE.md"
    cfg = SkillInstallConfig(
        agent_type=ExternalAgentType.CLAUDE_CODE,
        custom_target_path=target_file,
    )
    writer.install(cfg)
    assert target_file.exists()

    unres = writer.uninstall(cfg)
    assert unres.success is True
    assert unres.removed is True
    assert unres.file_deleted is True
    assert not target_file.exists()


def test_conflict_detector_identifies_legacy_tools() -> None:
    """Verify detector catches competing mem0 and legacy sqlite patterns."""
    text_with_conflict = "Please use mem0 tool to fetch user profile, or zep memory."
    report = MemoryPluginConflictDetector.inspect_content(text_with_conflict)
    assert report.has_conflict is True
    assert len(report.conflicting_rules) >= 2

    clean_text = "# Clean workspace instructions"
    clean_report = MemoryPluginConflictDetector.inspect_content(clean_text)
    assert clean_report.has_conflict is False
