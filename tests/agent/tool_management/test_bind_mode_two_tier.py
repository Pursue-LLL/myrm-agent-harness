"""ToolBindMode is TURN1 + RUNTIME_ONLY only."""

from __future__ import annotations

import pytest
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.tool_management.registry import ToolRegistry
from myrm_agent_harness.agent.tool_management.types import ToolBindMode, ToolSource


class _StubTool(BaseTool):
    name: str = "stub"
    description: str = "stub"

    def _run(self) -> str:
        return "ok"


def test_tool_bind_mode_has_no_discoverable_member() -> None:
    assert "DISCOVERABLE" not in ToolBindMode.__members__
    assert {m.value for m in ToolBindMode} == {"turn1", "runtime_only"}


def test_registry_public_api_has_runtime_tools_only() -> None:
    public = {name for name in dir(ToolRegistry) if not name.startswith("_")}
    assert "get_runtime_tools" in public
    assert not any("discoverable" in name.lower() for name in public)


def test_get_runtime_tools_returns_runtime_only_entries() -> None:
    reg = ToolRegistry()
    turn1 = _StubTool()
    turn1.name = "visible_tool"
    runtime = _StubTool()
    runtime.name = "_internal_hook"

    reg.register(turn1, source=ToolSource.META)
    reg.register(
        runtime, source=ToolSource.MIDDLEWARE, bind_mode=ToolBindMode.RUNTIME_ONLY
    )

    assert {t.name for t in reg.resolve()} == {"visible_tool"}
    assert {t.name for t in reg.get_runtime_tools()} == {"_internal_hook"}


@pytest.mark.asyncio
async def test_build_tools_accepts_three_arg_signature_only() -> None:
    from myrm_agent_harness.agent._internals._agent_build import (
        build_tools,
        create_registry,
    )

    registry = create_registry()
    resolved = await build_tools(registry, [], [])
    assert resolved == []
