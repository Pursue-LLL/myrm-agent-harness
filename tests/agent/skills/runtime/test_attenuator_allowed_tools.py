"""Tests for allowed-tools recognition in the trust attenuator.

Covers:
- tool names from other skill ecosystems (``Bash``, ``Read`` ...) never empty the toolset
- recognized names (registered or currently bound) keep exclusive-whitelist semantics
- trust ceilings are unaffected by ignored names
- ignored names produce one developer warning per skill
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from myrm_agent_harness.agent.skills.runtime import attenuator
from myrm_agent_harness.agent.skills.runtime.attenuator import READ_ONLY_TOOLS, attenuate_tools
from myrm_agent_harness.agent.tool_management.tool_layers import is_registered_action_tool
from myrm_agent_harness.backends.skills._runtime import build_skill_metadata
from myrm_agent_harness.backends.skills._utils import parse_skill_frontmatter
from myrm_agent_harness.backends.skills.types import SkillMetadata, SkillTrust

TOOLS = ["file_read_tool", "file_write_tool", "web_search_tool", "bash_code_execute_tool"]
ATTENUATOR_LOGGER = "myrm_agent_harness.agent.skills.runtime.attenuator"
IGNORED_WARNING = "allowed-tools"


@pytest.fixture(autouse=True)
def _fresh_warning_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test with an empty once-per-skill warning registry."""
    monkeypatch.setattr(attenuator, "_reported_ignored_entries", set())


def _skill(
    name: str,
    allowed_tools: list[str] | None,
    trust: SkillTrust = SkillTrust.TRUSTED,
    scanner_clean: bool = True,
) -> SkillMetadata:
    return SkillMetadata(
        name=name, description="test", trust=trust, scanner_clean=scanner_clean, allowed_tools=allowed_tools
    )


def _ignored_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == ATTENUATOR_LOGGER and IGNORED_WARNING in r.getMessage()]


def test_fixture_names_match_the_registry() -> None:
    assert all(is_registered_action_tool(name) for name in TOOLS)
    assert not is_registered_action_tool("Bash")
    assert not is_registered_action_tool("mcp_custom_tool")


class TestForeignEcosystemNames:
    def test_foreign_only_declaration_keeps_every_tool(self) -> None:
        result = attenuate_tools(TOOLS, [_skill("foreign-only", ["Bash", "Read", "Edit"])])

        assert result.tool_names == TOOLS
        assert result.removed_tools == []

    def test_foreign_only_declaration_keeps_the_single_tool_checked_at_execution(self) -> None:
        result = attenuate_tools(["file_write_tool"], [_skill("foreign-exec", ["Bash", "Write"])])

        assert result.tool_names == ["file_write_tool"]

    @pytest.mark.parametrize(
        "frontmatter",
        [
            pytest.param(
                "allowed-tools:\n  - Bash\n  - Read\n  - Edit\n  - Grep\n  - AskUserQuestion\n",
                id="yaml-list",
            ),
            pytest.param(
                "allowed-tools:\n  - Read\n  - Write\n  - Bash(ls *)\n  - Bash(mkdir *)\n",
                id="yaml-list-with-command-patterns",
            ),
            pytest.param("allowed-tools: Bash(link-cli:*) Read\n", id="space-delimited-string"),
        ],
    )
    def test_parsed_ecosystem_frontmatter_keeps_every_tool(self, frontmatter: str) -> None:
        content = f"---\nname: eco\ndescription: Ecosystem skill.\n{frontmatter}---\n\n# Eco\n"
        parsed = parse_skill_frontmatter(content, "eco")
        meta = build_skill_metadata("eco-parsed", parsed, str(Path("/tmp/eco")), content, SkillTrust.TRUSTED)

        assert meta.allowed_tools
        assert attenuate_tools(TOOLS, [meta]).tool_names == TOOLS

    def test_installed_skill_with_foreign_declaration_gets_the_read_only_ceiling(self) -> None:
        tools = sorted(READ_ONLY_TOOLS | {"file_write_tool", "web_search_tool"})
        skill = _skill("foreign-installed", ["Bash", "Write"], trust=SkillTrust.INSTALLED)

        result = attenuate_tools(tools, [skill])

        assert set(result.tool_names) == READ_ONLY_TOOLS


class TestRecognizedNames:
    def test_mixed_declaration_narrows_to_the_recognized_names(self) -> None:
        skill = _skill("mixed", ["Bash", "file_read_tool", "web_search_tool"])

        result = attenuate_tools(TOOLS, [skill])

        assert result.tool_names == ["file_read_tool", "web_search_tool"]
        assert result.removed_tools == ["file_write_tool", "bash_code_execute_tool"]

    def test_registered_declaration_is_an_exclusive_whitelist_even_when_unbound(self) -> None:
        result = attenuate_tools(["web_search_tool"], [_skill("registered", ["file_read_tool"])])

        assert result.tool_names == []

    def test_bound_name_outside_the_registry_is_recognized(self) -> None:
        tools = ["mcp_custom_tool", "file_read_tool"]

        result = attenuate_tools(tools, [_skill("bound-mcp", ["mcp_custom_tool"])])

        assert result.tool_names == ["mcp_custom_tool"]

    def test_bound_name_outside_the_trust_ceiling_still_counts_as_recognized(self) -> None:
        tools = ["mcp_custom_tool", *sorted(READ_ONLY_TOOLS)]
        skill = _skill("bound-mcp-installed", ["mcp_custom_tool"], trust=SkillTrust.INSTALLED)

        result = attenuate_tools(tools, [skill])

        assert result.tool_names == []


class TestMultipleSkills:
    def test_foreign_only_skill_does_not_widen_or_empty_a_native_skill(self) -> None:
        foreign = _skill("multi-foreign", ["Bash"])
        native = _skill("multi-native", ["file_read_tool"])

        assert attenuate_tools(TOOLS, [foreign, native]).tool_names == ["file_read_tool"]

    def test_foreign_only_skill_next_to_an_undeclared_skill_keeps_every_tool(self) -> None:
        foreign = _skill("multi-foreign-2", ["Bash"])
        undeclared = _skill("multi-undeclared", None)

        assert attenuate_tools(TOOLS, [foreign, undeclared]).tool_names == TOOLS


class TestIgnoredNameWarning:
    def test_warns_once_per_skill_with_the_ignored_names(self, caplog: pytest.LogCaptureFixture) -> None:
        skill = _skill("warn-once", ["Bash", "Read"])

        with caplog.at_level(logging.WARNING, logger=ATTENUATOR_LOGGER):
            attenuate_tools(TOOLS, [skill])
            attenuate_tools(TOOLS, [skill])

        warnings = _ignored_warnings(caplog)
        assert len(warnings) == 1
        assert "warn-once" in warnings[0]
        assert "Bash" in warnings[0]
        assert "Read" in warnings[0]

    def test_mixed_declaration_warns_about_the_ignored_part_only(self, caplog: pytest.LogCaptureFixture) -> None:
        skill = _skill("warn-mixed", ["Bash", "file_read_tool"])

        with caplog.at_level(logging.WARNING, logger=ATTENUATOR_LOGGER):
            attenuate_tools(TOOLS, [skill])

        warnings = _ignored_warnings(caplog)
        assert len(warnings) == 1
        assert "Bash" in warnings[0]
        assert "file_read_tool" not in warnings[0]

    def test_fully_recognized_declaration_does_not_warn(self, caplog: pytest.LogCaptureFixture) -> None:
        skill = _skill("warn-none", ["file_read_tool", "web_search_tool"])

        with caplog.at_level(logging.WARNING, logger=ATTENUATOR_LOGGER):
            attenuate_tools(TOOLS, [skill])

        assert _ignored_warnings(caplog) == []
