"""Behavioral tests for ``myrm_agent_harness.api.hooks`` and ``api.skills``."""

from __future__ import annotations

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
                "auto_extract_memories",
                "BackgroundJobFinishHandler",
                "BackgroundJobFinishResult",
                "BackgroundJobRecord",
                "BackgroundProcessInfo",
                "configure_background_job_store",
                "count_running_background_shell_jobs",
                "create_extraction_llm_func",
                "deferral_wait_s",
                "discard_shared_venv",
                "EVICTED_BASENAME_PATTERN",
                "GOAL_WAIT_KIND_KEY",
                "GOAL_WAIT_KIND_USAGE_LIMIT",
                "GOAL_WAIT_RESUME_AT_KEY",
                "get_background_job_store",
                "get_background_registry",
                "get_event_logger",
                "get_global_background_job_finish_handler",
                "get_memory_manager",
                "get_memory_runtime_budget",
                "get_memory_runtime_injection_contract",
                "get_memory_runtime_injection",
                "get_privacy_policy",
                "get_pseudonym_store",
                "get_task_intent",
                "get_terminal_errors",
                "get_workspace_root",
                "INPUT_WAIT_IDLE_SECONDS",
                "install_memory_pseudonymizer",
                "invalidate_permissions",
                "map_store_status_to_shell_task_status",
                "MountMode",
                "MountSpec",
                "MountValidationResult",
                "MountViolationType",
                "normalize_delivery_chat_id",
                "pause_goal_after_missed_wake",
                "PROVIDER_WINDOW_HOLD_MAX_S",
                "ProviderWindowHint",
                "build_evicted_basename",
                "build_pseudonym_store",
                "build_step_data",
                "persist_extracted_memories",
                "persist_terminal_state",
                "persist_vault_log_ref",
                "read_evicted_line_range",
                "restore_memory_pseudonymizer",
                "set_api_key_refresher",
                "set_approval_user_id",
                "set_global_background_job_finish_handler",
                "set_permission_invalidation_callback",
                "set_privacy_policy",
                "set_pseudonym_store",
                "set_security_config",
                "set_task_intent",
                "set_workspace_root",
                "validate_and_sanitize_mounts",
                "validate_mount_spec",
            ],
        ),
        (
            "myrm_agent_harness.api.skills",
            [
                "SkillInstallResult",
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


_HOOKS_NON_CALLABLE_EXPORTS: frozenset[str] = frozenset(
    {
        "EVICTED_BASENAME_PATTERN",
        "GOAL_WAIT_KIND_KEY",
        "GOAL_WAIT_KIND_USAGE_LIMIT",
        "GOAL_WAIT_RESUME_AT_KEY",
        "INPUT_WAIT_IDLE_SECONDS",
        "PROVIDER_WINDOW_HOLD_MAX_S",
    }
)


@pytest.mark.api
def test_api_hooks_callables_are_functions() -> None:
    from myrm_agent_harness.api import hooks

    for name in hooks.__all__:
        if name in _HOOKS_NON_CALLABLE_EXPORTS:
            continue
        value = getattr(hooks, name)
        assert callable(value), f"{name} should be callable"


@pytest.mark.api
def test_api_hooks_session_context_defaults() -> None:
    from myrm_agent_harness.api.hooks import (
        get_event_logger,
        get_memory_manager,
        get_memory_runtime_budget,
        get_memory_runtime_injection,
        get_memory_runtime_injection_contract,
        get_terminal_errors,
    )

    assert get_memory_manager() is None
    assert get_memory_runtime_budget() is None
    assert get_memory_runtime_injection() is None
    assert get_memory_runtime_injection_contract()["states"] == ("applied", "not_applied")
    assert get_event_logger() is None
    assert get_terminal_errors() is not None


@pytest.mark.api
def test_api_hooks_background_registry_singleton() -> None:
    from myrm_agent_harness.api.hooks import get_background_registry

    first = get_background_registry()
    second = get_background_registry()
    assert first is second


@pytest.mark.api
def test_api_hooks_discard_shared_venv_resolves_active_execution_config(tmp_path: Path) -> None:
    from myrm_agent_harness.api.hooks import discard_shared_venv
    from myrm_agent_harness.toolkits.code_execution.config import (
        ExecutionConfig,
        get_execution_config,
        set_execution_config,
    )

    venv_dir = tmp_path / "venvs"
    (venv_dir / "lib").mkdir(parents=True)
    previous = get_execution_config()
    config = ExecutionConfig()
    config.local.shared_venv_path = str(venv_dir)
    set_execution_config(config)
    try:
        assert discard_shared_venv() is True
        assert not venv_dir.exists()
        assert discard_shared_venv() is False
    finally:
        set_execution_config(previous)


@pytest.mark.api
def test_api_hooks_running_shell_job_count_delegates_to_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    from myrm_agent_harness.api import hooks

    queried: list[str | None] = []

    class _FakeRegistry:
        def count_running(self, session_id: str | None = None) -> int:
            queried.append(session_id)
            return 3 if session_id is None else 1

    monkeypatch.setattr(hooks, "get_background_registry", _FakeRegistry)

    assert hooks.count_running_background_shell_jobs() == 3
    assert hooks.count_running_background_shell_jobs("session-a") == 1
    assert queried == [None, "session-a"]


@pytest.mark.api
def test_api_hooks_workspace_root_binds_both_layers_within_its_own_context() -> None:
    import contextvars

    from myrm_agent_harness.api.hooks import get_workspace_root, set_workspace_root
    from myrm_agent_harness.core.context_vars import workspace_root_var

    def bind_and_read() -> tuple[str, str]:
        set_workspace_root("/workspace/demo")
        return get_workspace_root(), workspace_root_var.get()

    assert contextvars.copy_context().run(bind_and_read) == ("/workspace/demo", "/workspace/demo")
    assert get_workspace_root() != "/workspace/demo"


@pytest.mark.api
def test_api_hooks_memory_pseudonymizer_install_returns_previous_and_restore_reinstates_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import contextvars

    from myrm_agent_harness.agent._internals import run_lifecycle
    from myrm_agent_harness.api.hooks import install_memory_pseudonymizer, restore_memory_pseudonymizer
    from myrm_agent_harness.core.security.persistence.content_scan import (
        get_pii_pseudonymizer,
        set_pii_pseudonymizer,
    )

    def original(text: str) -> str:
        return text

    def replacement(_text: str) -> str:
        return "[masked]"

    registered: list[tuple[object, object]] = []

    def fake_register(policy: object, store: object) -> None:
        registered.append((policy, store))
        set_pii_pseudonymizer(replacement)

    monkeypatch.setattr(run_lifecycle, "_register_pii_pseudonymizer", fake_register)

    def scenario() -> None:
        set_pii_pseudonymizer(original)
        previous = install_memory_pseudonymizer("policy", "store")
        assert previous is original
        assert get_pii_pseudonymizer() is replacement
        restore_memory_pseudonymizer(previous)
        assert get_pii_pseudonymizer() is original

    contextvars.copy_context().run(scenario)
    assert registered == [("policy", "store")]


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
