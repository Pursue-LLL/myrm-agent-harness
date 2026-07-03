"""Default Agent must not bind control-plane orchestrator tools.

These names are listed in ``tool_layers.py`` for registry accounting only.
They must not inflate Turn-1 ``bind_tools`` (Prefix Cache protection).
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.middlewares.completion_guard import COMPLETION_CHECK_TOOL_NAME

CONTROL_PLANE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "dispatch_research",
        "think",
        "finalize_report",
        "submit_verdict",
        "_completion_check",
    }
)

SCHEMA_ONLY_CONTROL_PLANE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "dispatch_research",
        "think",
        "finalize_report",
        "submit_verdict",
    }
)

PTC_RUNTIME_TOOL_NAMES: frozenset[str] = frozenset({"spawn_subagent", "notify"})


@pytest.mark.asyncio
async def test_default_resolve_excludes_internal_pseudo_tools() -> None:
    """Default build_tools + CompletionGuard: internal names stay out of resolve()."""
    from myrm_agent_harness.agent._internals._agent_build import (
        build_middlewares,
        build_tools,
        create_registry,
    )

    registry = create_registry()
    middlewares = build_middlewares(registry, [])

    resolved = await build_tools(registry, [], [], middlewares)
    resolved_names = {tool.name for tool in resolved}

    overlap = resolved_names & CONTROL_PLANE_TOOL_NAMES
    assert not overlap, f"Control-plane tools leaked into default bind_tools: {sorted(overlap)}"


@pytest.mark.asyncio
async def test_completion_check_is_runtime_only_not_turn1() -> None:
    """CompletionGuard registers _completion_check as runtime-only middleware tool."""
    from myrm_agent_harness.agent._internals._agent_build import (
        build_middlewares,
        build_tools,
        create_registry,
    )
    from myrm_agent_harness.agent.tool_management.types import ToolBindMode

    registry = create_registry()
    middlewares = build_middlewares(registry, [])

    await build_tools(registry, [], [], middlewares)

    runtime_names = {tool.name for tool in registry.get_runtime_tools()}
    assert COMPLETION_CHECK_TOOL_NAME in runtime_names

    discoverable_names = {tool.name for tool in registry.get_discoverable_tools()}
    assert COMPLETION_CHECK_TOOL_NAME not in discoverable_names

    active_names = {tool.name for tool in registry.resolve()}
    assert COMPLETION_CHECK_TOOL_NAME not in active_names

    entry = next(e for e in registry._entries if e.tool.name == COMPLETION_CHECK_TOOL_NAME)
    assert entry.bind_mode == ToolBindMode.RUNTIME_ONLY


@pytest.mark.asyncio
async def test_schema_only_tools_not_registered_in_default_build() -> None:
    """DR / verifier signal tools are not registered unless their subsystems run."""
    from myrm_agent_harness.agent._internals._agent_build import (
        build_middlewares,
        build_tools,
        create_registry,
    )

    registry = create_registry()
    middlewares = build_middlewares(registry, [])

    await build_tools(registry, [], [], middlewares)

    for name in SCHEMA_ONLY_CONTROL_PLANE_TOOL_NAMES:
        assert not registry.has_tool(name), f"{name} must not be in default registry"


def test_ptc_runtime_tools_not_in_tool_layers_registry() -> None:
    """DW PTC bridge tools are runtime-only; must not inflate _TOOL_LAYERS."""
    from myrm_agent_harness.agent.tool_management.tool_layers import _TOOL_LAYERS

    overlap = set(_TOOL_LAYERS) & PTC_RUNTIME_TOOL_NAMES
    assert not overlap, f"PTC runtime tools must not be in _TOOL_LAYERS: {sorted(overlap)}"
