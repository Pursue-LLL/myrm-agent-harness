"""Behavioral tests for ``myrm_agent_harness.api.hooks`` and ``api.skills``."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

_MINIMAL_SKILL_MD = """---
name: demo-skill
description: Demo skill for api.skills smoke test.
---

# Demo
"""


@pytest.mark.api
@pytest.mark.parametrize(
    ("module_name", "expected_all"),
    [
        (
            "myrm_agent_harness.api.hooks",
            [
                "create_extraction_llm_func",
                "get_background_registry",
                "get_event_logger",
                "get_memory_manager",
                "get_task_intent",
                "get_terminal_errors",
                "invalidate_permissions",
                "persist_extracted_memories",
                "set_approval_user_id",
                "set_permission_invalidation_callback",
                "set_task_intent",
            ],
        ),
        (
            "myrm_agent_harness.api.skills",
            [
                "SkillMetadataError",
                "build_skill_metadata",
                "compute_content_hash",
                "parse_skill_frontmatter",
                "update_frontmatter_evolution_lock",
            ],
        ),
    ],
)
def test_api_submodule_exports_match_all(module_name: str, expected_all: list[str]) -> None:
    module = __import__(module_name, fromlist=["__all__"])
    assert sorted(module.__all__) == sorted(expected_all)


@pytest.mark.api
def test_api_hooks_callables_are_functions() -> None:
    from myrm_agent_harness.api import hooks

    for name in hooks.__all__:
        value = getattr(hooks, name)
        assert inspect.isfunction(value), f"{name} should be a function"


@pytest.mark.api
def test_api_hooks_session_context_defaults() -> None:
    from myrm_agent_harness.api.hooks import (
        get_event_logger,
        get_memory_manager,
        get_terminal_errors,
    )

    assert get_memory_manager() is None
    assert get_event_logger() is None
    assert get_terminal_errors() is not None


@pytest.mark.api
def test_api_hooks_background_registry_singleton() -> None:
    from myrm_agent_harness.api.hooks import get_background_registry

    first = get_background_registry()
    second = get_background_registry()
    assert first is second


@pytest.mark.api
def test_api_skills_parse_and_hash_roundtrip() -> None:
    from myrm_agent_harness.api.skills import compute_content_hash, parse_skill_frontmatter

    frontmatter = parse_skill_frontmatter(_MINIMAL_SKILL_MD, "demo-skill")
    assert frontmatter.description.startswith("Demo skill")
    assert frontmatter.name == "demo-skill"

    digest = compute_content_hash(_MINIMAL_SKILL_MD)
    assert digest.startswith("sha256:")
    assert digest == compute_content_hash(_MINIMAL_SKILL_MD)


@pytest.mark.api
def test_api_skills_build_metadata_and_update_lock(tmp_path: Path) -> None:
    from myrm_agent_harness.api.skills import (
        build_skill_metadata,
        parse_skill_frontmatter,
        update_frontmatter_evolution_lock,
    )
    from myrm_agent_harness.backends.skills.types import SkillTrust

    skill_md = tmp_path / "SKILL.md"
    skill_md.write_text(_MINIMAL_SKILL_MD, encoding="utf-8")

    frontmatter = parse_skill_frontmatter(_MINIMAL_SKILL_MD, "demo-skill")
    metadata = build_skill_metadata(
        skill_name="demo-skill",
        frontmatter=frontmatter,
        storage_path=str(tmp_path),
        content=_MINIMAL_SKILL_MD,
        trust=SkillTrust.TRUSTED,
    )
    assert metadata.name == "demo-skill"

    update_frontmatter_evolution_lock(skill_md, locked=True)
    updated = skill_md.read_text(encoding="utf-8")
    assert "evolution_locked: true" in updated


@pytest.mark.api
def test_api_skills_metadata_error_on_invalid_frontmatter() -> None:
    from myrm_agent_harness.api.skills import SkillMetadataError, parse_skill_frontmatter

    with pytest.raises(SkillMetadataError):
        parse_skill_frontmatter("---\nname: broken\n---\n", "broken")
