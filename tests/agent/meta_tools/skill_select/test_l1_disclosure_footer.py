"""Tests for L1 disclosure footer (linked files + config block)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from myrm_agent_harness.agent.meta_tools.skills.select.l1_disclosure_footer import (
    build_l1_disclosure_footer,
    filter_disclosable_resource_paths,
    format_compact_linked_index,
    format_config_section,
    format_linked_files_section,
    group_linked_resources,
    resolve_config_display_values,
)
from myrm_agent_harness.backends.skills.types import (
    MCPSkillData,
    SkillInstance,
    SkillInstanceConfig,
    SkillMetadata,
)
from tests.mocks.skill_backend import InMemorySkillBackend


def _make_skill(**overrides: object) -> SkillMetadata:
    base = SkillMetadata(
        name="deploy_skill",
        description="Deploy workflow",
        storage_skill_id="deploy_skill",
        storage_path="/tmp/skills/deploy_skill",
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def _make_instance(**config_overrides: object) -> SkillInstance:
    now = datetime.now(UTC)
    config = SkillInstanceConfig(
        instance_name="personal",
        skill_name="deploy_skill",
        created_at=now,
        updated_at=now,
        config_overrides=dict(config_overrides),
    )
    return SkillInstance(
        metadata=_make_skill(),
        instance_name="personal",
        config=config,
        state={},
    )


class TestFilterDisclosableResourcePaths:
    def test_keeps_allowed_subdirs_only(self) -> None:
        raw = [
            "scripts/deploy.sh",
            "references/runbook.md",
            "LICENSE.txt",
            ".stats.json",
            "scripts/.hidden.sh",
            "../escape.md",
        ]
        assert filter_disclosable_resource_paths(raw) == [
            "references/runbook.md",
            "scripts/deploy.sh",
        ]

    def test_groups_and_caps(self) -> None:
        grouped = group_linked_resources(
            [f"scripts/file{i}.sh" for i in range(12)] + ["references/a.md", "templates/t.md"]
        )
        section = format_linked_files_section(grouped, max_per_group=3, max_total=5)
        assert "[Linked files]" in section
        assert "scripts: scripts/file0.sh" in section
        assert "more" in section

    def test_nested_allowed_paths(self) -> None:
        paths = filter_disclosable_resource_paths(["assets/images/icons/logo.png", "src/main.py"])
        assert paths == ["assets/images/icons/logo.png"]

    def test_compact_index(self) -> None:
        paths = [f"scripts/f{i}.sh" for i in range(10)]
        compact = format_compact_linked_index(paths, max_paths=3)
        assert compact.startswith("Linked:")
        assert "(+7 more)" in compact


class TestConfigSection:
    def test_merges_schema_default_and_override(self) -> None:
        skill = _make_skill(
            config_schema={
                "type": "object",
                "properties": {
                    "wiki.path": {"type": "string", "default": "/default/wiki"},
                    "timeout": {"type": "integer", "default": 30},
                },
            }
        )
        instance = _make_instance(**{"wiki.path": "/vault/foo"})
        resolved = resolve_config_display_values(skill, instance)
        assert resolved["wiki.path"] == "/vault/foo"
        assert resolved["timeout"] == 30

    def test_redacts_secrets_in_config_block(self) -> None:
        skill = _make_skill(
            config_schema={
                "type": "object",
                "properties": {"api_key": {"type": "string"}},
            }
        )
        instance = _make_instance(api_key="sk-test1234567890abcdef1234567890ab")
        section = format_config_section(
            skill,
            instance,
            resolve_config_display_values(skill, instance),
        )
        assert "sk-test1234567890abcdef1234567890ab" not in section
        assert "[Skill config (instance: personal)]" in section


@pytest.mark.asyncio
async def test_build_footer_includes_linked_and_config() -> None:
    backend = InMemorySkillBackend()
    skill = _make_skill(
        config_schema={
            "type": "object",
            "properties": {"wiki.path": {"type": "string", "default": "/wiki"}},
        }
    )
    backend.add_skill(
        skill,
        content="# Deploy\n\nRun the script.",
        resources={
            "scripts/deploy.sh": b"echo deploy",
            "references/checklist.md": b"# checklist",
        },
    )
    instance = _make_instance(**{"wiki.path": "/custom"})

    footer = await build_l1_disclosure_footer(skill, backend, instance)
    assert "[Linked files]" in footer
    assert "scripts/deploy.sh" in footer
    assert "references/checklist.md" in footer
    assert "wiki.path = /custom" in footer


@pytest.mark.asyncio
async def test_build_footer_empty_for_mcp_skill() -> None:
    skill = _make_mcp_skill()
    backend = InMemorySkillBackend()
    footer = await build_l1_disclosure_footer(skill, backend, None)
    assert footer == ""


def _make_mcp_skill() -> SkillMetadata:
    return SkillMetadata(
        name="mcp_skill",
        description="MCP",
        mcp=MCPSkillData(server="s", tools=[], config=[], tool_schemas={}),
    )
