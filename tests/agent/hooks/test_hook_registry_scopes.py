"""HookRegistry scoped groups: hooks whose lifetime is shorter than the session registry."""

from __future__ import annotations

from myrm_agent_harness.agent.hooks.registry import HookRegistry
from myrm_agent_harness.agent.hooks.types import (
    HOOK_PRIORITY_SECURITY,
    CommandHookDefinition,
    HookDefinition,
    HookEvent,
)


def _cmd(command: str, **fields: int) -> CommandHookDefinition:
    return CommandHookDefinition(command=command, **fields)


def _commands(registry: HookRegistry, event: HookEvent = HookEvent.PRE_TOOL_USE) -> list[str]:
    return [hook.command for hook in registry.get(event) if isinstance(hook, CommandHookDefinition)]


def test_release_removes_only_the_scope_hooks() -> None:
    registry = HookRegistry()
    registry.register(HookEvent.PRE_TOOL_USE, _cmd("session"))

    assert registry.activate_scope("skill:a", [(HookEvent.PRE_TOOL_USE, _cmd("a1")), (HookEvent.SESSION_END, _cmd("a2"))])
    assert registry.activate_scope("skill:b", [(HookEvent.PRE_TOOL_USE, _cmd("b1"))])
    registry.release_scope("skill:a")

    assert _commands(registry) == ["session", "b1"]
    assert _commands(registry, HookEvent.SESSION_END) == []
    assert registry.total_count == 2


def test_scope_can_be_activated_again_after_release() -> None:
    registry = HookRegistry()
    hooks = [(HookEvent.PRE_TOOL_USE, _cmd("a"))]

    for _ in range(3):
        assert registry.activate_scope("skill:a", hooks)
        assert _commands(registry) == ["a"]
        registry.release_scope("skill:a")
        assert _commands(registry) == []


def test_activating_an_active_scope_keeps_the_original_owner() -> None:
    registry = HookRegistry()
    hooks = [(HookEvent.PRE_TOOL_USE, _cmd("a"))]

    assert registry.activate_scope("skill:a", hooks) is True
    assert registry.activate_scope("skill:a", [(HookEvent.PRE_TOOL_USE, _cmd("dup"))]) is False

    assert _commands(registry) == ["a"]
    registry.release_scope("skill:a")
    registry.release_scope("skill:a")
    assert registry.total_count == 0


def test_release_matches_by_identity_not_equality() -> None:
    registry = HookRegistry()
    first, second = _cmd("same"), _cmd("same")
    assert first == second and first is not second

    registry.activate_scope("a", [(HookEvent.PRE_TOOL_USE, first)])
    registry.activate_scope("b", [(HookEvent.PRE_TOOL_USE, second)])
    registry.release_scope("b")

    (remaining,) = registry.get(HookEvent.PRE_TOOL_USE)
    assert remaining is first


def test_release_of_unknown_scope_is_a_noop() -> None:
    registry = HookRegistry()
    registry.register(HookEvent.PRE_TOOL_USE, _cmd("kept"))

    registry.release_scope("never-activated")

    assert _commands(registry) == ["kept"]


def test_clear_forgets_scopes() -> None:
    registry = HookRegistry()
    registry.activate_scope("skill:a", [(HookEvent.PRE_TOOL_USE, _cmd("a"))])

    registry.clear()

    assert registry.total_count == 0
    assert registry.activate_scope("skill:a", [(HookEvent.PRE_TOOL_USE, _cmd("a"))])


def test_released_events_leave_no_empty_headings_in_the_summary() -> None:
    registry = HookRegistry()
    registry.activate_scope("skill:a", [(HookEvent.SESSION_END, _cmd("a"))])
    registry.release_scope("skill:a")

    assert registry.summary() == ""


def test_priority_order_is_unaffected_by_scoped_registration() -> None:
    registry = HookRegistry()
    registry.register(HookEvent.PRE_TOOL_USE, _cmd("early"))
    registry.activate_scope("skill:a", [(HookEvent.PRE_TOOL_USE, _cmd("scoped"))])
    registry.register(HookEvent.PRE_TOOL_USE, _cmd("guard", priority=HOOK_PRIORITY_SECURITY))

    ordered: list[HookDefinition] = registry.get(HookEvent.PRE_TOOL_USE)

    assert [hook.command for hook in ordered if isinstance(hook, CommandHookDefinition)] == ["guard", "early", "scoped"]
