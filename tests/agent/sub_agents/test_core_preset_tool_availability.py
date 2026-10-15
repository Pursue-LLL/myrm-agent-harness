"""Core subagent preset tool availability — SCIP guardrail tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from langchain_core.tools import BaseTool, StructuredTool

from myrm_agent_harness.agent.sub_agents.builder import filter_tools
from myrm_agent_harness.agent.sub_agents.config_loader import SubagentConfigLoader
from myrm_agent_harness.agent.sub_agents.types import SubagentConfig
from myrm_agent_harness.agent.sub_agents.verifier_selection import resolve_verifier
from myrm_agent_harness.agent.tool_management.tool_layers import _TOOL_LAYERS


def _monorepo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent.parent


def _core_presets_dir() -> Path:
    path = _monorepo_root() / "myrm-agent" / "myrm-agent-server" / "app" / "config" / "subagents" / "core"
    if not path.exists():
        pytest.skip("Core subagent presets directory not found")
    return path


def _make_tool(name: str) -> BaseTool:
    return StructuredTool.from_function(
        func=lambda: name,
        name=name,
        description=f"Mock tool {name}",
    )


def _full_parent_toolkit() -> list[BaseTool]:
    return [_make_tool(name) for name in sorted(_TOOL_LAYERS.keys())]


_CORE_PRESET_NAMES: tuple[str, ...] = (
    "search",
    "browser",
    "analysis",
    "coding",
    "deep-audit",
    "adversarial-reviewer",
)


@pytest.mark.parametrize("preset_name", _CORE_PRESET_NAMES)
def test_core_preset_loads_and_has_tools_after_filter(preset_name: str) -> None:
    yaml_path = _core_presets_dir() / f"{preset_name}.yaml"
    if not yaml_path.exists():
        pytest.skip(f"Preset not found: {yaml_path}")

    loader = SubagentConfigLoader()
    config = loader.load_from_yaml(yaml_path, expected_name=preset_name)

    assert config is not None
    assert config.tools, f"{preset_name} preset must declare at least one tool"

    filtered = filter_tools(config, _full_parent_toolkit())
    assert filtered, f"{preset_name} preset produced zero tools after filter_tools; allowlist={list(config.tools)}"


def test_browser_preset_includes_interact_tool() -> None:
    yaml_path = _core_presets_dir() / "browser.yaml"
    loader = SubagentConfigLoader()
    config = loader.load_from_yaml(yaml_path, expected_name="browser")

    assert config is not None
    assert "browser_interact_tool" in config.tools

    filtered_names = {tool.name for tool in filter_tools(config, _full_parent_toolkit())}
    assert "browser_interact_tool" in filtered_names


def test_analysis_preset_uses_memory_ssot_tools() -> None:
    yaml_path = _core_presets_dir() / "analysis.yaml"
    loader = SubagentConfigLoader()
    config = loader.load_from_yaml(yaml_path, expected_name="analysis")

    assert config is not None
    assert set(config.tools) == {
        "memory_search_tool",
        "memory_save_tool",
        "memory_manage_tool",
    }


@pytest.mark.asyncio
async def test_cron_verifier_preset_can_run_commands() -> None:
    """Cron verifies with this fixed preset and has no spawn-time preflight, so a preset edit that drops the
    command tool would turn every cron verification into an inconclusive one without any error."""
    config = SubagentConfigLoader().load_from_yaml(
        _core_presets_dir() / "adversarial-reviewer.yaml", expected_name="adversarial-reviewer"
    )
    catalog = AsyncMock()
    catalog.resolve = AsyncMock(return_value=config)

    verifier_type, _ = await resolve_verifier(
        catalog,
        "adversarial-reviewer",
        "adversarial-reviewer",
        SubagentConfig(system_prompt="worker"),
        _full_parent_toolkit(),
    )

    assert verifier_type == "adversarial-reviewer"
