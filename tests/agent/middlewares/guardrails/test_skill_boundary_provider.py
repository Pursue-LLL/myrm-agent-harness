"""Tests for SkillBoundaryProvider.

Covers async/sync permission checker compatibility across the guardrail
evaluate/aevaluate paths, loaded-skill gating, and allow-by-default semantics.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.middlewares.guardrails.core import GuardrailRequest
from myrm_agent_harness.agent.middlewares.guardrails.providers.skill_boundary import (
    PermissionChecker,
    SkillBoundaryProvider,
)
from myrm_agent_harness.agent.skill_agent.context import (
    reset_loaded_skills,
    set_loaded_skills,
)
from myrm_agent_harness.backends.skills.permission_validator import (
    map_permission_to_skill_permission,
)
from myrm_agent_harness.backends.skills.types_metadata import SkillMetadata


@pytest.fixture(autouse=True)
def _reset_loaded_skills() -> None:
    reset_loaded_skills()
    yield
    reset_loaded_skills()


def _load_skill(name: str = "demo_skill") -> None:
    set_loaded_skills([SkillMetadata(name=name, description="demo", version="1.0.0")])


def _request(tool_name: str = "file_write_tool") -> GuardrailRequest:
    return GuardrailRequest(
        tool_name=tool_name,
        tool_input={"path": "/tmp/x.txt"},
    )


@pytest.mark.asyncio
async def test_aevaluate_allows_with_async_checker_when_granted() -> None:
    """Async checker allowing the permission must let the tool call through."""
    _load_skill()

    async def checker(skill_id: str, permission_type: str, operation: str) -> tuple[bool, str]:
        return True, ""

    provider = SkillBoundaryProvider(permission_checker=checker)
    decision = await provider.aevaluate(_request())
    assert decision.allow is True


@pytest.mark.asyncio
async def test_aevaluate_denies_with_async_checker_when_not_granted() -> None:
    """No loaded skill with the required permission must deny the tool call."""
    _load_skill()

    async def checker(skill_id: str, permission_type: str, operation: str) -> tuple[bool, str]:
        return False, "denied by policy"

    provider = SkillBoundaryProvider(permission_checker=checker)
    decision = await provider.aevaluate(_request("bash_code_execute_tool"))
    assert decision.allow is False
    assert decision.reasons[0].code == "skill_boundary.violation"


@pytest.mark.asyncio
async def test_aevaluate_allows_when_no_skills_loaded() -> None:
    """No loaded skills must short-circuit to allow."""

    def fail_checker(skill_id: str, permission_type: str, operation: str) -> tuple[bool, str]:
        pytest.fail("checker must not be called when no skills are loaded")

    provider = SkillBoundaryProvider(permission_checker=fail_checker)
    decision = await provider.aevaluate(_request("bash_code_execute_tool"))
    assert decision.allow is True


@pytest.mark.asyncio
async def test_aevaluate_allows_when_tool_has_no_permission_mapping() -> None:
    """Tools without a permission mapping must not invoke the checker."""
    _load_skill()
    provider = SkillBoundaryProvider(permission_checker=MagicMock())
    decision = await provider.aevaluate(_request("foo_tool"))
    assert decision.allow is True
    provider._permission_checker.assert_not_called()


@pytest.mark.asyncio
async def test_aevaluate_compatible_with_sync_checker() -> None:
    """A sync checker returning a plain tuple must still work via aevaluate."""
    _load_skill()
    provider = SkillBoundaryProvider(permission_checker=lambda _skill_id, _pt, _op: (True, ""))
    decision = await provider.aevaluate(_request())
    assert decision.allow is True


def test_evaluate_wraps_async_checker_via_asyncio_run() -> None:
    """The sync protocol method must resolve async checkers without nesting."""
    _load_skill()

    async def checker(skill_id: str, permission_type: str, operation: str) -> tuple[bool, str]:
        return True, ""

    provider = SkillBoundaryProvider(permission_checker=checker)
    decision = provider.evaluate(_request())
    assert decision.allow is True


def test_evaluate_denies_async_checker_when_not_granted() -> None:
    """Sync path must surface deny decisions from async checkers."""
    _load_skill()

    async def checker(skill_id: str, permission_type: str, operation: str) -> tuple[bool, str]:
        return False, "denied"

    provider = SkillBoundaryProvider(permission_checker=checker)
    decision = provider.evaluate(_request("bash_code_execute_tool"))
    assert decision.allow is False


def test_evaluate_allow_without_checker() -> None:
    """A provider without a permission checker must always allow."""
    provider = SkillBoundaryProvider()
    assert provider.evaluate(_request("bash_code_execute_tool")).allow is True


@pytest.mark.asyncio
async def test_aevaluate_allow_without_checker() -> None:
    provider = SkillBoundaryProvider()
    assert (await provider.aevaluate(_request("bash_code_execute_tool"))).allow is True


@pytest.mark.asyncio
async def test_aevaluate_runs_inside_existing_event_loop() -> None:
    """The async path must never call asyncio.run() inside the running loop."""
    _load_skill()

    async def checker(skill_id: str, permission_type: str, operation: str) -> tuple[bool, str]:
        # Assert that we are inside the running event loop.
        assert asyncio.get_running_loop() is not None
        return True, ""

    provider = SkillBoundaryProvider(permission_checker=checker)
    decision = await provider.aevaluate(_request())
    assert decision.allow is True


def _granted_checker(granted: frozenset[str]) -> PermissionChecker:
    """Checker that models the server-side DB grant lookup by permission type.

    Mirrors ``permission_service``: the SSOT permission type is mapped to its
    SkillPermission, then compared against the granted permission values.
    """

    async def checker(skill_id: str, permission_type: str, operation: str) -> tuple[bool, str]:
        mapped = map_permission_to_skill_permission(permission_type)
        if mapped is not None and mapped.value in granted:
            return True, ""
        return False, f"denied: {permission_type} not granted"

    return checker


@pytest.mark.asyncio
async def test_ssot_file_edit_maps_to_file_write_gate() -> None:
    """file_edit_tool must resolve via SSOT to file_write (no heuristic drift).

    Previously the boundary heuristic missed the tool name and silently allowed
    edits without FILE_WRITE. Regression guard for the drift.
    """
    _load_skill()
    provider = SkillBoundaryProvider(permission_checker=_granted_checker(frozenset({"file_read"})))
    decision = await provider.aevaluate(
        GuardrailRequest(
            tool_name="file_edit_tool",
            tool_input={"path": "/workspace/x.py", "edits": [{"old": "a", "new": "b"}]},
        )
    )
    assert decision.allow is False
    assert "file_write" in decision.reasons[0].message


@pytest.mark.asyncio
async def test_ssot_grep_maps_to_file_read_gate() -> None:
    """grep_tool must resolve via SSOT to file_read and be gated without grant."""
    _load_skill()
    provider = SkillBoundaryProvider(permission_checker=_granted_checker(frozenset()))
    decision = await provider.aevaluate(
        GuardrailRequest(
            tool_name="grep_tool",
            tool_input={"pattern": "secret", "path": "/workspace"},
        )
    )
    assert decision.allow is False
    assert "file_read" in decision.reasons[0].message


@pytest.mark.asyncio
async def test_ssot_bash_code_execute_uses_code_interpreter_grant() -> None:
    """bash_code_execute_tool must resolve via SSOT to code_interpreter.

    Previously the heuristic attributed it to shell_exec, wrongly rejecting a
    skill granted CODE_INTERPRETER (sandboxed code execution).
    """
    _load_skill()
    provider = SkillBoundaryProvider(permission_checker=_granted_checker(frozenset({"code_interpreter"})))
    decision = await provider.aevaluate(
        GuardrailRequest(tool_name="bash_code_execute_tool", tool_input={"command": "echo hi"})
    )
    assert decision.allow is True


@pytest.mark.asyncio
async def test_ssot_web_fetch_uses_network_access_grant() -> None:
    """web_fetch_tool must resolve via SSOT to net_fetch → NETWORK_ACCESS grant."""
    _load_skill()
    provider = SkillBoundaryProvider(permission_checker=_granted_checker(frozenset({"network_access"})))
    decision = await provider.aevaluate(
        GuardrailRequest(tool_name="web_fetch_tool", tool_input={"url": "https://example.com"})
    )
    assert decision.allow is True


@pytest.mark.asyncio
async def test_ssot_mcp_tool_not_applicable_to_skills() -> None:
    """MCP tools resolve to mcp_invoke (own auth) and must not invoke the checker."""
    _load_skill()
    provider = SkillBoundaryProvider(permission_checker=MagicMock())
    decision = await provider.aevaluate(GuardrailRequest(tool_name="mcp__github__get_repo", tool_input={"repo": "x"}))
    assert decision.allow is True
    provider._permission_checker.assert_not_called()


def test_extract_critical_params_falls_back_to_full_input() -> None:
    """Tools outside the file/shell/network branches must echo the whole input."""
    provider = SkillBoundaryProvider()
    result = provider._extract_critical_params("env_tool", {"key": "HOME"})
    assert result == str({"key": "HOME"})


def test_resolve_loaded_skills_swallows_context_failure() -> None:
    """A failure reading loaded skills must degrade to an empty list (allow)."""
    import myrm_agent_harness.agent.skill_agent.context as ctx

    def _boom() -> list[object]:
        raise RuntimeError("context unavailable")

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(ctx, "get_loaded_skills", _boom)
    try:
        provider = SkillBoundaryProvider()
        assert provider._resolve_loaded_skills() == []
    finally:
        monkeypatch.undo()


@pytest.mark.asyncio
async def test_aevaluate_allows_when_any_loaded_skill_has_permission() -> None:
    """One granted skill must authorize the call even if others lack it."""
    set_loaded_skills(
        [
            SkillMetadata(name="skill-a", description="d", version="1.0.0"),
            SkillMetadata(name="skill-b", description="d", version="1.0.0"),
        ]
    )
    granted = frozenset({"code_interpreter"})

    async def checker(skill_id: str, permission_type: str, operation: str) -> tuple[bool, str]:
        if skill_id == "skill-b":
            mapped = map_permission_to_skill_permission(permission_type)
            return mapped is not None and mapped.value in granted, ""
        return False, "denied"

    provider = SkillBoundaryProvider(permission_checker=checker)
    decision = await provider.aevaluate(
        GuardrailRequest(tool_name="bash_code_execute_tool", tool_input={"command": "echo hi"})
    )
    assert decision.allow is True


@pytest.mark.asyncio
async def test_aevaluate_uses_storage_skill_id_over_name() -> None:
    """A skill with a storage id must be checked under that id, not its name."""
    set_loaded_skills(
        [
            SkillMetadata(
                name="display-name",
                description="d",
                version="1.0.0",
                storage_skill_id="stored-id",
            )
        ]
    )

    async def checker(skill_id: str, permission_type: str, operation: str) -> tuple[bool, str]:
        return skill_id == "stored-id", ""

    provider = SkillBoundaryProvider(permission_checker=checker)
    decision = await provider.aevaluate(GuardrailRequest(tool_name="file_write_tool", tool_input={"path": "/tmp/x"}))
    assert decision.allow is True
