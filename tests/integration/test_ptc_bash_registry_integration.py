"""PTC builtin registry ↔ bash tool description integration.

Verifies create_bash_code_execute_tool appends live registry description without web PTC stubs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.meta_tools.bash.bash_code_execute_tool import create_bash_code_execute_tool
from myrm_agent_harness.agent.skills.mcp.builtin_registry import get_builtin_tool_registry
from myrm_agent_harness.agent.skills.mcp.ipc_proxy import IPCCallContext, _ipc_call_context


def _ipc_ctx(session_id: str, workspace_root: Path) -> IPCCallContext:
    return IPCCallContext(
        session_id=session_id,
        workspace_root=str(workspace_root),
        trace_id="integ",
    )


@pytest.mark.integration
def test_bash_tool_description_merges_registry_without_web_stubs() -> None:
    import myrm_agent_harness.agent.skills.mcp.builtin_registry as registry_mod

    registry_mod._registry = None
    registry = get_builtin_tool_registry()
    ptc_section = registry.get_ptc_description()

    bash_tool = create_bash_code_execute_tool()
    description = bash_tool.description

    assert ptc_section in description
    assert "myrm_tools.session_store" in ptc_section
    assert "myrm_tools.notify" in ptc_section
    assert "myrm_tools.web_search(" not in ptc_section
    assert "myrm_tools.web_fetch(" not in ptc_section
    assert "函数名/参数与 Agent tool schema 一致" in description
    assert "myrm_tools.web_search_tool" not in description
    assert "单次调用仍用 native tool" in description
    assert set(registry.tool_names) == {"session_store", "session_load", "session_keys", "notify"}
    registry_mod._registry = None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_registry_dispatch_rejects_unknown_tool() -> None:
    import myrm_agent_harness.agent.skills.mcp.builtin_registry as registry_mod

    registry_mod._registry = None
    registry = get_builtin_tool_registry()
    with pytest.raises(KeyError, match="not found"):
        await registry.dispatch("web_search", {"query": "x"})
    registry_mod._registry = None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_registry_dispatch_session_keys_real_handler(tmp_path: Path) -> None:
    import myrm_agent_harness.agent.skills.mcp.builtin_registry as registry_mod

    registry_mod._registry = None
    registry = get_builtin_tool_registry()
    token = _ipc_call_context.set(_ipc_ctx("integ-session", tmp_path))
    try:
        await registry.dispatch("session_store", {"key": "integ-key", "value": 42})
        keys = await registry.dispatch("session_keys", {})
        assert isinstance(keys, list)
        assert "integ-key" in keys

        loaded = await registry.dispatch("session_load", {"key": "integ-key"})
        assert loaded == 42
    finally:
        _ipc_call_context.reset(token)
        registry_mod._registry = None
