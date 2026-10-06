"""SkillAgent hook lifecycle: skill-declared hooks coexist with framework default hooks.

Skill-declared command/http hooks share the registry's event lists with the
framework's callable hooks; the lifecycle init must tell them apart.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.hooks import get_hook_executor
from myrm_agent_harness.agent.hooks.executor import HookRegistry
from myrm_agent_harness.agent.hooks.types import (
    CallableHookDefinition,
    CommandHookDefinition,
    HookDefinition,
    HookEvent,
    HookSource,
    HttpHookDefinition,
)
from myrm_agent_harness.agent.skill_agent import SkillAgent
from myrm_agent_harness.backends.skills.types import SkillMetadata


def _skill(*hooks: tuple[HookEvent, HookDefinition]) -> SkillMetadata:
    return SkillMetadata(name="probe_skill", description="probe", hooks=list(hooks))


def _callable_names(registry: HookRegistry, event: HookEvent) -> list[str]:
    return [hook.fn.__name__ for hook in registry.get(event) if isinstance(hook, CallableHookDefinition)]


def _session_registry() -> HookRegistry:
    executor = get_hook_executor()
    assert executor is not None
    return executor.registry


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hook",
    [
        CommandHookDefinition(command="echo ok", source=HookSource.SKILL),
        HttpHookDefinition(url="https://example.invalid/hook", source=HookSource.SKILL),
    ],
    ids=["command", "http"],
)
async def test_non_callable_skill_hook_on_pre_tool_use_does_not_break_init(hook: HookDefinition) -> None:
    agent = SkillAgent(llm=AsyncMock())

    await agent._init_hook_lifecycle(_skill((HookEvent.PRE_TOOL_USE, hook)), "m1", "query")

    registry = _session_registry()
    assert hook in registry.get(HookEvent.PRE_TOOL_USE)
    assert _callable_names(registry, HookEvent.PRE_TOOL_USE) == ["on_pre_tool_use"]


@pytest.mark.asyncio
async def test_framework_hooks_register_once_per_session() -> None:
    agent = SkillAgent(llm=AsyncMock())

    await agent._init_hook_lifecycle(None, "m1", "query")
    await agent._init_hook_lifecycle(None, "m2", "query")

    registry = _session_registry()
    assert _callable_names(registry, HookEvent.PRE_TOOL_USE) == ["on_pre_tool_use"]
    assert _callable_names(registry, HookEvent.APPROVAL_CORRECTION) == ["on_approval_correction"]
