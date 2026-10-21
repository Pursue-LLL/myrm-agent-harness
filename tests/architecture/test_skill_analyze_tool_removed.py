"""Architecture gate: skill_analyze Agent tool must not exist (Curator GUI is SSOT)."""

from __future__ import annotations

from pathlib import Path


def test_skill_analyze_meta_tool_package_removed() -> None:
    analyze_dir = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "myrm_agent_harness"
        / "agent"
        / "meta_tools"
        / "skills"
        / "analyze"
    )
    assert not analyze_dir.exists()


def test_skill_analyze_not_in_tool_layers() -> None:
    from myrm_agent_harness.agent.tool_management.tool_layers import _TOOL_LAYERS

    assert "skill_analyze_tool" not in _TOOL_LAYERS
