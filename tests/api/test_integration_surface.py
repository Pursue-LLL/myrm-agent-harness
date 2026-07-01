"""Smoke tests for ``myrm_agent_harness.api.hooks`` and ``api.skills``."""

from __future__ import annotations

import inspect

import pytest


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
                "get_terminal_errors",
                "invalidate_permissions",
                "persist_extracted_memories",
                "set_approval_user_id",
                "set_permission_invalidation_callback",
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
def test_api_skills_exports() -> None:
    from myrm_agent_harness.api import skills

    assert inspect.isclass(skills.SkillMetadataError)
    assert issubclass(skills.SkillMetadataError, Exception)
    for name in (
        "build_skill_metadata",
        "compute_content_hash",
        "parse_skill_frontmatter",
        "update_frontmatter_evolution_lock",
    ):
        assert callable(getattr(skills, name))
