"""Unit tests for SkillExecutor MCP config resolution across subagent routing passes.

[INPUT]
- myrm_agent_harness.agent.skills.mcp::executor (POS: PTC detection and MCP config lookup)
- myrm_agent_harness.agent.skills.runtime::registry (POS: runtime skill registry with the IPC MCP skill cache)

[OUTPUT]
- Coverage of SkillExecutor.get_skill_mcp_config and detect_and_prepare, including the lookup that must
  survive a concurrent MCP-less subagent clearing the registry.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.skills.mcp.executor import SkillExecutor
from myrm_agent_harness.agent.skills.runtime.registry import SkillRegistry
from myrm_agent_harness.backends.skills.types import MCPSkillData, SkillMetadata
from myrm_agent_harness.toolkits.code_execution import MCPConfigItem

_PTC_COMMAND = 'python3 -c "from skills.demo_skill import ping"'


@pytest.fixture
def registry(monkeypatch: pytest.MonkeyPatch) -> SkillRegistry:
    """Swap the process-wide registry SkillExecutor resolves at call time for an empty one."""
    fresh = SkillRegistry()
    monkeypatch.setattr("myrm_agent_harness.agent.skills.runtime.registry.skill_registry", fresh)
    return fresh


def _mcp_skill(name: str, config: list[dict[str, object]]) -> SkillMetadata:
    return SkillMetadata(
        name=name,
        description=f"MCP skill {name}",
        mcp=MCPSkillData(server=name, tools=[], config=config),
    )


def _demo_config() -> list[dict[str, object]]:
    return [{"name": "demo", "type": "stdio", "command": "echo", "args": ["hi"]}]


_DEMO_ITEMS = [MCPConfigItem(name="demo", type="stdio", command="echo", args=["hi"])]


class TestGetSkillMcpConfig:
    def test_returns_config_items_of_a_registered_mcp_skill(self, registry: SkillRegistry) -> None:
        registry.register(_mcp_skill("demo_skill", _demo_config()))

        assert SkillExecutor().get_skill_mcp_config("demo_skill") == _DEMO_ITEMS

    def test_config_survives_a_concurrent_registry_clear(self, registry: SkillRegistry) -> None:
        """An in-flight parent PTC call keeps its MCP config when an MCP-less subagent clears the registry."""
        registry.register(_mcp_skill("demo_skill", _demo_config()))

        registry.clear_mcp_skills()

        assert registry.get_skill("demo_skill") is None
        assert SkillExecutor().get_skill_mcp_config("demo_skill") == _DEMO_ITEMS

    def test_unknown_skill_has_no_config(self, registry: SkillRegistry) -> None:
        assert SkillExecutor().get_skill_mcp_config("missing_skill") is None

    def test_storage_skill_has_no_mcp_config(self, registry: SkillRegistry) -> None:
        registry.register(
            SkillMetadata(
                name="user_skill",
                description="Storage skill",
                storage_skill_id="skill_user",
                storage_path="/skills/user",
            )
        )

        assert SkillExecutor().get_skill_mcp_config("user_skill") is None

    def test_mcp_skill_without_config_has_no_config(self, registry: SkillRegistry) -> None:
        registry.register(_mcp_skill("empty_skill", []))

        assert SkillExecutor().get_skill_mcp_config("empty_skill") is None


class TestDetectAndPrepare:
    def test_returns_the_config_of_the_imported_mcp_skill(self, registry: SkillRegistry) -> None:
        registry.register(_mcp_skill("demo_skill", _demo_config()))

        assert SkillExecutor().detect_and_prepare(_PTC_COMMAND) == (True, _DEMO_ITEMS)

    def test_detects_a_ptc_import_of_a_skill_that_is_no_longer_registered(self, registry: SkillRegistry) -> None:
        assert SkillExecutor().detect_and_prepare(_PTC_COMMAND) == (True, None)

    def test_command_without_ptc_import_is_not_a_skill_call(self, registry: SkillRegistry) -> None:
        assert SkillExecutor().detect_and_prepare('python3 -c "print(1)"') == (False, None)


class TestDetectPtcImportForms:
    """Every static import form must route into PTC, not just ``from x import y``."""

    @pytest.mark.parametrize(
        ("code", "expected"),
        [
            ("from skills.demo_skill import ping", (True, "demo_skill")),
            ("from demo_skill import ping", (True, "demo_skill")),
            ("import skills.demo_skill", (True, "demo_skill")),
            ("import skills.demo_skill as s", (True, "demo_skill")),
            ("from skills.demo_skill import ping as p", (True, "demo_skill")),
            ("from skills.demo_skill.sub import helper", (True, "demo_skill")),
            ("import importlib\nm = importlib.import_module('skills.demo_skill')", (True, "demo_skill")),
            ("m = __import__('skills.demo_skill')", (True, "demo_skill")),
            ("from tools.notify import notify", (True, "__builtin__")),
            ("import tools.notify", (True, "__builtin__")),
            ("print('no imports here')", (False, None)),
            ("import json\nimport os", (False, None)),
        ],
    )
    def test_ast_detection_matrix(self, code: str, expected: tuple[bool, str | None]) -> None:
        assert SkillExecutor()._detect_ptc_in_code(code) == expected

    def test_unparseable_code_falls_back_to_regex(self) -> None:
        """Truncated scripts still route via the regex fallback."""
        code = "from skills.demo_skill import ping\nif x =="  # SyntaxError
        assert SkillExecutor()._detect_ptc_in_code(code) == (True, "demo_skill")

    def test_dynamic_module_name_is_not_guessed(self) -> None:
        """A computed module name cannot be resolved statically; stay non-PTC."""
        code = "import importlib\nname = 'skills.' + 'demo' + '_skill'\nimportlib.import_module(name)"
        assert SkillExecutor()._detect_ptc_in_code(code) == (False, None)
