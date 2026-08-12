"""Tests for SkillBoundaryProvider.

Covers async/sync permission checker compatibility across the guardrail
evaluate/aevaluate paths, loaded-skill gating, and allow-by-default semantics.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.middlewares.guardrails.core import GuardrailRequest
from myrm_agent_harness.agent.middlewares.guardrails.providers.skill_boundary import (
    SkillBoundaryProvider,
)
from myrm_agent_harness.agent.skill_agent.context import (
    reset_loaded_skills,
    set_loaded_skills,
)
from myrm_agent_harness.backends.skills.types_metadata import SkillMetadata


@pytest.fixture(autouse=True)
def _reset_loaded_skills() -> None:
    reset_loaded_skills()
    yield
    reset_loaded_skills()


def _load_skill(name: str = "demo_skill") -> None:
    set_loaded_skills(
        [SkillMetadata(name=name, description="demo", version="1.0.0")]
    )


def _request(tool_name: str = "file_write") -> GuardrailRequest:
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
    decision = await provider.aevaluate(_request("shell_exec"))
    assert decision.allow is False
    assert decision.reasons[0].code == "skill_boundary.violation"


@pytest.mark.asyncio
async def test_aevaluate_allows_when_no_skills_loaded() -> None:
    """No loaded skills must short-circuit to allow."""
    def fail_checker(skill_id: str, permission_type: str, operation: str) -> tuple[bool, str]:
        pytest.fail("checker must not be called when no skills are loaded")

    provider = SkillBoundaryProvider(permission_checker=fail_checker)
    decision = await provider.aevaluate(_request("shell_exec"))
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
    provider = SkillBoundaryProvider(
        permission_checker=lambda _skill_id, _pt, _op: (True, "")
    )
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
    decision = provider.evaluate(_request("shell_exec"))
    assert decision.allow is False


def test_evaluate_allow_without_checker() -> None:
    """A provider without a permission checker must always allow."""
    provider = SkillBoundaryProvider()
    assert provider.evaluate(_request("shell_exec")).allow is True


@pytest.mark.asyncio
async def test_aevaluate_allow_without_checker() -> None:
    provider = SkillBoundaryProvider()
    assert (await provider.aevaluate(_request("shell_exec"))).allow is True


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
