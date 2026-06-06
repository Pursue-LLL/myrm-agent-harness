"""Unit tests for _build_available_types_hint — dynamic type discovery for DW."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from myrm_agent_harness.agent.dynamic_workflow import _build_available_types_hint


@dataclass
class FakeSubagentConfig:
    system_prompt: str = ""
    description: str = ""
    display_name: str = ""


class FakeCatalog:
    """Mock SubagentCatalog for testing."""

    def __init__(self, configs: dict[str, FakeSubagentConfig]) -> None:
        self._configs = configs

    async def list_available(self) -> list[str]:
        return list(self._configs.keys())

    async def resolve(self, type_id: str) -> FakeSubagentConfig | None:
        return self._configs.get(type_id)


class EmptyCatalog:
    async def list_available(self) -> list[str]:
        return []

    async def resolve(self, type_id: str) -> None:
        return None


@pytest.mark.asyncio
async def test_catalog_path_lists_all_types():
    """With catalog, all available types are listed with descriptions."""
    catalog = FakeCatalog(
        {
            "coding": FakeSubagentConfig(description="Coding specialist", system_prompt="Code."),
            "analysis": FakeSubagentConfig(description="Data analyst", system_prompt="Analyze."),
        }
    )
    result = await _build_available_types_hint(catalog)

    assert '"coding": Coding specialist' in result
    assert '"analysis": Data analyst' in result
    assert '"generalPurpose"' in result


@pytest.mark.asyncio
async def test_catalog_path_fallback_to_display_name():
    """When description is empty, display_name is used."""
    catalog = FakeCatalog(
        {
            "custom": FakeSubagentConfig(display_name="Custom Agent", system_prompt="Custom."),
        }
    )
    result = await _build_available_types_hint(catalog)

    assert '"custom": Custom Agent' in result


@pytest.mark.asyncio
async def test_catalog_path_fallback_to_system_prompt():
    """When description and display_name are empty, system_prompt[:80] is used."""
    long_prompt = "You are a senior legal advisor specializing in contract review, compliance checks, and risk assessment workflows."
    catalog = FakeCatalog(
        {
            "legal-uuid": FakeSubagentConfig(system_prompt=long_prompt),
        }
    )
    result = await _build_available_types_hint(catalog)

    assert '"legal-uuid"' in result
    assert "senior legal advisor" in result
    assert len(long_prompt[:80]) == 80
    # UUID itself should NOT appear as the description
    assert "legal-uuid\n" not in result.replace('"legal-uuid": ', "")


@pytest.mark.asyncio
async def test_catalog_path_empty_returns_empty():
    """Empty catalog returns empty string."""
    result = await _build_available_types_hint(EmptyCatalog())
    assert result == ""


@pytest.mark.asyncio
async def test_catalog_path_cap_at_50():
    """More than 50 types are capped with a remainder message."""
    configs = {f"agent-{i}": FakeSubagentConfig(description=f"Agent {i}", system_prompt="x") for i in range(60)}
    catalog = FakeCatalog(configs)
    result = await _build_available_types_hint(catalog)

    assert "... and 10 more available." in result
    lines_with_agents = [line for line in result.split("\n") if line.startswith('- "agent-')]
    assert len(lines_with_agents) == 50


@pytest.mark.asyncio
async def test_fallback_path_no_catalog():
    """Without catalog (None), falls back to global SUBAGENT_CONFIGS."""
    result = await _build_available_types_hint(None)
    # In bare test env, SUBAGENT_CONFIGS is empty
    assert result == ""


@pytest.mark.asyncio
async def test_fallback_path_with_populated_registry(monkeypatch):
    """Fallback path uses SUBAGENT_CONFIGS when populated."""
    fake_registry = {
        "search": FakeSubagentConfig(description="Web search agent", system_prompt="Search."),
        "browser": FakeSubagentConfig(description="Browser automation", system_prompt="Browse."),
    }
    monkeypatch.setattr(
        "myrm_agent_harness.agent.sub_agents.registry.SUBAGENT_CONFIGS",
        fake_registry,
    )
    result = await _build_available_types_hint(None)

    assert '"browser": Browser automation' in result
    assert '"search": Web search agent' in result
    assert '"generalPurpose"' in result


@pytest.mark.asyncio
async def test_resolve_returns_none_skipped():
    """If resolve returns None for a type_id, it's silently skipped."""

    class PartialCatalog:
        async def list_available(self) -> list[str]:
            return ["exists", "ghost"]

        async def resolve(self, type_id: str) -> FakeSubagentConfig | None:
            if type_id == "exists":
                return FakeSubagentConfig(description="Real agent", system_prompt="Real.")
            return None

    result = await _build_available_types_hint(PartialCatalog())

    assert '"exists": Real agent' in result
    assert "ghost" not in result.split('"generalPurpose"')[0]


@pytest.mark.asyncio
async def test_all_fields_empty_uses_empty_prompt_slice():
    """When description, display_name, and system_prompt are all empty, uses empty slice gracefully."""
    catalog = FakeCatalog(
        {
            "empty-agent": FakeSubagentConfig(system_prompt="", description="", display_name=""),
        }
    )
    result = await _build_available_types_hint(catalog)

    assert '"empty-agent": ' in result
    assert "Available agent_type values" in result


@pytest.mark.asyncio
async def test_exactly_50_types_no_overflow_message():
    """Exactly 50 types should NOT produce '... and 0 more available.' message."""
    configs = {f"agent-{i}": FakeSubagentConfig(description=f"Agent {i}", system_prompt="x") for i in range(50)}
    catalog = FakeCatalog(configs)
    result = await _build_available_types_hint(catalog)

    assert "... and" not in result
    lines_with_agents = [line for line in result.split("\n") if line.startswith('- "agent-')]
    assert len(lines_with_agents) == 50


@pytest.mark.asyncio
async def test_catalog_general_purpose_always_appended():
    """generalPurpose is always appended even when it's already in catalog."""
    catalog = FakeCatalog(
        {
            "generalPurpose": FakeSubagentConfig(description="Custom GP", system_prompt="GP."),
        }
    )
    result = await _build_available_types_hint(catalog)

    lines = result.split("\n")
    gp_lines = [line for line in lines if "generalPurpose" in line]
    assert len(gp_lines) == 2


@pytest.mark.asyncio
async def test_fallback_path_sorted_alphabetically(monkeypatch):
    """Fallback path sorts SUBAGENT_CONFIGS alphabetically by key."""
    fake_registry = {
        "zulu": FakeSubagentConfig(description="Zulu agent", system_prompt="Z."),
        "alpha": FakeSubagentConfig(description="Alpha agent", system_prompt="A."),
        "mike": FakeSubagentConfig(description="Mike agent", system_prompt="M."),
    }
    monkeypatch.setattr(
        "myrm_agent_harness.agent.sub_agents.registry.SUBAGENT_CONFIGS",
        fake_registry,
    )
    result = await _build_available_types_hint(None)

    lines = [line for line in result.split("\n") if line.startswith('- "')]
    agent_lines = [line for line in lines if "generalPurpose" not in line]
    assert agent_lines[0].startswith('- "alpha"')
    assert agent_lines[1].startswith('- "mike"')
    assert agent_lines[2].startswith('- "zulu"')


@pytest.mark.asyncio
async def test_fallback_no_description_uses_name(monkeypatch):
    """Fallback path: when config.description is empty, uses the config key (name)."""
    fake_registry = {
        "no-desc": FakeSubagentConfig(description="", system_prompt="Some prompt"),
    }
    monkeypatch.setattr(
        "myrm_agent_harness.agent.sub_agents.registry.SUBAGENT_CONFIGS",
        fake_registry,
    )
    result = await _build_available_types_hint(None)

    assert '"no-desc": no-desc' in result
