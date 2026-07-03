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
async def test_completion_check_is_deferred_not_active() -> None:
    """CompletionGuard registers _completion_check as deferred middleware tool."""
    from myrm_agent_harness.agent._internals._agent_build import (
        build_middlewares,
        build_tools,
        create_registry,
    )

    registry = create_registry()
    middlewares = build_middlewares(registry, [])

    await build_tools(registry, [], [], middlewares)

    deferred_names = {tool.name for tool in registry.get_deferred_tools()}
    assert COMPLETION_CHECK_TOOL_NAME in deferred_names

    active_names = {tool.name for tool in registry.resolve()}
    assert COMPLETION_CHECK_TOOL_NAME not in active_names


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
