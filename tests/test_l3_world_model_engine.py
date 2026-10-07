# [POS] tests/test_l3_world_model_engine.py
# [INPUT] L3WorldModelEngine, L3WorldModelField, ProjectEnvironmentSnapshot, RuntimeEnvironmentInfo
# [OUTPUT] TestL3WorldModelEngineSuite

"""Unit tests for L3 World Model macro memory execution engine."""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory import (
    L3WorldModelEngine,
    L3WorldModelField,
    ProjectEnvironmentSnapshot,
    RuntimeEnvironmentInfo,
)


def test_record_initialization_and_default_state() -> None:
    """Verify new project creates an isolated record with default versioning."""
    engine = L3WorldModelEngine()
    record = engine.get_or_create_record("myrm-test-project")

    assert record.project_id == "myrm-test-project"
    assert record.version == 1
    assert record.general_rules == ""
    assert record.project_environment == ""
    assert record.project_contract == ""
    assert record.domain_knowledge == ""


def test_dimension_update_and_optimistic_versioning() -> None:
    """Verify updating a dimension bumps version number and tracks source refs."""
    engine = L3WorldModelEngine()
    record = engine.update_dimension(
        project_id="proj_alpha",
        field_name=L3WorldModelField.GENERAL_RULES,
        content="Rule: Strict zero Any typing.",
        source_ref="agent_rule_config",
    )

    assert record.version == 2
    assert record.general_rules == "Rule: Strict zero Any typing."
    assert "agent_rule_config" in record.source_refs

    # Update second dimension
    record2 = engine.update_dimension(
        project_id="proj_alpha",
        field_name=L3WorldModelField.PROJECT_CONTRACT,
        content="Contract: Server must not import deep harness internals.",
        source_ref="arch_gate",
    )

    assert record2.version == 3
    assert record2.project_contract == "Contract: Server must not import deep harness internals."
    assert "arch_gate" in record2.source_refs


def test_merge_environment_snapshot() -> None:
    """Verify integrating multi-runtime ProjectEnvironmentSnapshot formats cleanly."""
    engine = L3WorldModelEngine()
    snapshot = ProjectEnvironmentSnapshot(
        workspace_name="open-perplexity",
        runtimes=[
            RuntimeEnvironmentInfo(
                name="Python",
                version="3.13.13",
                package_manager="uv/poetry",
                key_dependencies=["fastapi", "pydantic", "qdrant-client"],
            ),
            RuntimeEnvironmentInfo(
                name="Node.js",
                version="22.14.0",
                package_manager="pnpm",
                key_dependencies=["react", "tailwindcss", "vite"],
            ),
        ],
        config_markers=["pyproject.toml", "package.json", "_ARCH.md"],
    )

    record = engine.merge_environment_snapshot("proj_alpha", snapshot)
    assert record.version == 2
    env_text = record.project_environment

    assert "Workspace: open-perplexity" in env_text
    assert "Python 3.13.13 via uv/poetry" in env_text
    assert "Node.js 22.14.0 via pnpm" in env_text
    assert "pyproject.toml, package.json, _ARCH.md" in env_text


def test_render_macro_context_with_active_constraints() -> None:
    """Verify full macro context assembling and boundary delimiter formatting."""
    engine = L3WorldModelEngine()
    engine.update_dimension(
        project_id="proj_beta",
        field_name=L3WorldModelField.GENERAL_RULES,
        content="Rule 1: Performance first.",
    )
    engine.update_dimension(
        project_id="proj_beta",
        field_name=L3WorldModelField.PROJECT_CONTRACT,
        content="Architecture: Monorepo with unidirectional layering.",
    )

    payload = engine.render_macro_context("proj_beta")
    assert payload.project_id == "proj_beta"
    assert payload.version == 3
    assert payload.has_active_constraints is True
    assert payload.token_estimate > 0

    rendered = payload.rendered_markdown
    assert "<!-- L3_WORLD_MODEL_BEGIN -->" in rendered
    assert "<!-- L3_WORLD_MODEL_END -->" in rendered
    assert "Rule 1: Performance first." in rendered
    assert "Architecture: Monorepo with unidirectional layering." in rendered


def test_render_macro_context_empty_baseline() -> None:
    """Verify clean fallback rendering when no macro constraints have been configured."""
    engine = L3WorldModelEngine()
    payload = engine.render_macro_context("empty_project")

    assert payload.project_id == "empty_project"
    assert payload.has_active_constraints is False
    assert "[NO_MACRO_CONSTRAINTS_DEFINED]" in payload.rendered_markdown
    assert "<!-- L3_WORLD_MODEL_BEGIN -->" in payload.rendered_markdown
    assert "<!-- L3_WORLD_MODEL_END -->" in payload.rendered_markdown
