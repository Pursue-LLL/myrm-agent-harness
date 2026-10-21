"""Integration: real MemoryManager (SQLite) → ContextVar → MemoryContextMiddleware injection.

Assembles the production chain with real persistence:
- Real ``SQLiteRelationalStore`` on a temp file.
- Real ``MemoryManager`` (relational-only, no embedding/vector needed for context load).
- Real ``memory_context_middleware`` and a real ``ModelRequest``.

Only the downstream LLM handler is stubbed to capture the overridden ModelRequest.
Covers both RecallMode.HYBRID (memory_search_tool bound → guidance tail) and
RecallMode.CONTEXT (no tools → context without tool guidance), plus cold-start
and rule injection through the real relational store.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from langchain.agents.middleware import ModelRequest
from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.middlewares.memory_context.memory_context_format import (
    MEMORY_CONTEXT_MARKER,
    MEMORY_UNTRUSTED_OPEN_MARKER,
)
from myrm_agent_harness.agent.middlewares.memory_context.memory_context_middleware import (
    memory_context_middleware,
)
from myrm_agent_harness.agent.skill_agent.context import (
    get_memory_runtime_injection,
    set_memory_manager,
    set_memory_runtime_budget,
    set_memory_runtime_injection,
)
from myrm_agent_harness.toolkits.memory.config import MemoryConfig, RecallMode
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.relational import SQLiteRelationalStore

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture
async def manager_factory(
    tmp_path: Path,
) -> Callable[[RecallMode], MemoryManager]:
    """Build a real MemoryManager per test; closes the SQLite store afterwards."""
    stores: list[SQLiteRelationalStore] = []

    def _factory(recall_mode: RecallMode) -> MemoryManager:
        store = SQLiteRelationalStore(str(tmp_path / f"memory_{len(stores)}.db"))
        stores.append(store)
        cfg = MemoryConfig(
            embedding_model="test-model",
            max_learned_context_chars=2000,
            model_context_tokens=8000,
        )
        return MemoryManager(
            cfg,
            user_id="integration-user",
            relational=store,
            auto_warmup=False,
            recall_mode=recall_mode,
        )

    yield _factory
    for store in stores:
        await store.close()
    set_memory_manager(None)
    set_memory_runtime_budget(None)
    set_memory_runtime_injection(None)


@pytest.fixture
def memory_search_tool() -> object:
    """Real BaseTool named memory_search_tool (binding detection by name)."""
    from langchain_core.tools import BaseTool

    class _MemorySearchTool(BaseTool):
        name: str = "memory_search_tool"
        description: str = "Search user memory across corpora"

        def _run(self, *args: object, **kwargs: object) -> str:  # pragma: no cover - not invoked
            return "no-op"

    return _MemorySearchTool()


def _make_request(
    *,
    messages: list[object],
    tools: list[object],
    state_messages: list[object] | None = None,
) -> ModelRequest:
    runtime = SimpleNamespace(context={"chat_id": "integration-chat"})
    return ModelRequest(
        model=AsyncMock(),
        messages=messages,
        tools=tools,
        state={"messages": state_messages if state_messages is not None else []},
        runtime=runtime,
    )


async def _run_middleware(
    request: ModelRequest,
) -> tuple[list[object], dict[str, str | None]]:
    """Run the real middleware and capture the overridden ModelRequest + injection status."""
    captured: list[object] = []

    async def handler(inner: ModelRequest):
        captured.extend(inner.messages)
        return AsyncMock()

    await memory_context_middleware.awrap_model_call(request, handler)

    status = get_memory_runtime_injection() or {}
    return captured, {
        "state": str(status.get("state")),
        "reason": str(status.get("reason")) if status.get("reason") else None,
        "source": str(status.get("source")) if status.get("source") else None,
    }


# ---------------------------------------------------------------------------
# HYBRID mode — memory_search_tool bound, guidance tail expected
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hybrid_real_assembly_injects_profile_with_guidance(
    manager_factory: Callable[[RecallMode], MemoryManager],
    memory_search_tool: object,
) -> None:
    """Real profile flows from SQLite into the stable SystemMessage with the guidance tail."""
    manager = manager_factory(RecallMode.HYBRID)
    await manager.set_profile_attribute("name", "Alice Real")

    set_memory_manager(manager)
    request = _make_request(
        messages=[SystemMessage(content="sys prefix"), HumanMessage(content="hello")],
        tools=[memory_search_tool],
    )

    messages, status = await _run_middleware(request)

    assert status["state"] == "applied"
    assert status["source"] == "fallback"
    stable_msgs = [
        m for m in messages if isinstance(m, SystemMessage) and MEMORY_CONTEXT_MARKER in str(m.content)
    ]
    assert len(stable_msgs) == 1
    stable = str(stable_msgs[0].content)
    assert "Alice Real" in stable
    assert "## Memory Search" in stable
    assert "memory_search_tool" in stable
    assert "## Citation Requirements" in stable
    assert "<cite:MEMORY_ID>" in stable
    assert MEMORY_UNTRUSTED_OPEN_MARKER not in stable


@pytest.mark.asyncio
async def test_hybrid_real_assembly_injects_rules(
    manager_factory: Callable[[RecallMode], MemoryManager],
    memory_search_tool: object,
) -> None:
    """Real procedural rules written via the manager surface land in the stable block."""
    manager = manager_factory(RecallMode.HYBRID)
    await manager.add_rule("deploy", "run tests first", priority=10)

    set_memory_manager(manager)
    request = _make_request(
        messages=[SystemMessage(content="sys prefix"), HumanMessage(content="deploy now")],
        tools=[memory_search_tool],
    )

    messages, status = await _run_middleware(request)

    assert status["state"] == "applied"
    stable_payload = "\n".join(
        str(m.content) for m in messages if isinstance(m, SystemMessage) and MEMORY_CONTEXT_MARKER in str(m.content)
    )
    assert "## Behavioral Rules" in stable_payload
    assert "When: deploy" in stable_payload
    assert "Do: run tests first" in stable_payload


@pytest.mark.asyncio
async def test_hybrid_real_assembly_injects_working_state(
    manager_factory: Callable[[RecallMode], MemoryManager],
    memory_search_tool: object,
) -> None:
    """Real working_state profile keys flow into the Active Working Context section."""
    from datetime import datetime

    from myrm_agent_harness.toolkits.memory._internal.storage_context import (
        WORKING_STATE_PROFILE_KEY,
        WORKING_STATE_UPDATED_AT_KEY,
    )

    manager = manager_factory(RecallMode.HYBRID)
    store = manager._relational
    assert store is not None
    await store.set_profile(
        WORKING_STATE_PROFILE_KEY,
        "mid-task: drafting the migration plan",
        scope=manager._scope,
    )
    await store.set_profile(
        WORKING_STATE_UPDATED_AT_KEY,
        datetime.now(UTC).isoformat(),
        scope=manager._scope,
    )

    set_memory_manager(manager)
    request = _make_request(
        messages=[SystemMessage(content="sys prefix"), HumanMessage(content="hello")],
        tools=[memory_search_tool],
    )

    messages, status = await _run_middleware(request)

    assert status["state"] == "applied"
    stable_payload = "\n".join(
        str(m.content) for m in messages if isinstance(m, SystemMessage) and MEMORY_CONTEXT_MARKER in str(m.content)
    )
    assert "## Active Working Context" in stable_payload
    assert "mid-task: drafting the migration plan" in stable_payload


@pytest.mark.asyncio
async def test_hybrid_real_assembly_injects_agent_instructions(
    manager_factory: Callable[[RecallMode], MemoryManager],
    memory_search_tool: object,
) -> None:
    """Real AGENT_SELF procedural memories render as Your Self-Instructions."""
    from myrm_agent_harness.toolkits.memory.types import RuleSource

    manager = manager_factory(RecallMode.HYBRID)
    await manager.add_rule("always", "be concise", priority=5, source=RuleSource.AGENT_SELF)

    set_memory_manager(manager)
    request = _make_request(
        messages=[SystemMessage(content="sys prefix"), HumanMessage(content="hello")],
        tools=[memory_search_tool],
    )

    messages, status = await _run_middleware(request)

    assert status["state"] == "applied"
    stable_payload = "\n".join(
        str(m.content) for m in messages if isinstance(m, SystemMessage) and MEMORY_CONTEXT_MARKER in str(m.content)
    )
    assert "## Your Self-Instructions" in stable_payload
    assert "be concise" in stable_payload


@pytest.mark.asyncio
async def test_hybrid_real_assembly_cold_start(
    manager_factory: Callable[[RecallMode], MemoryManager],
    memory_search_tool: object,
) -> None:
    """Empty real store → HYBRID still injects Discovery Mode guidance."""
    manager = manager_factory(RecallMode.HYBRID)

    set_memory_manager(manager)
    request = _make_request(
        messages=[SystemMessage(content="sys prefix"), HumanMessage(content="hello")],
        tools=[memory_search_tool],
    )

    messages, status = await _run_middleware(request)

    assert status["state"] == "applied"
    stable_msgs = [m for m in messages if isinstance(m, SystemMessage) and "Discovery Mode" in str(m.content)]
    assert len(stable_msgs) == 1
    stable = str(stable_msgs[0].content)
    assert MEMORY_CONTEXT_MARKER in stable
    assert "## Memory Search" in stable


@pytest.mark.asyncio
async def test_hybrid_real_assembly_budget_truncation_notice(
    manager_factory: Callable[[RecallMode], MemoryManager],
    memory_search_tool: object,
) -> None:
    """Real oversized profile set is clipped and the notice references the bound search tool."""
    manager = manager_factory(RecallMode.HYBRID)
    store = manager._relational
    assert store is not None
    for i in range(80):
        await store.set_profile(f"k{i}", "w" * 300, scope=manager._scope)

    set_memory_manager(manager)
    request = _make_request(
        messages=[SystemMessage(content="sys prefix"), HumanMessage(content="hello")],
        tools=[memory_search_tool],
    )

    messages, status = await _run_middleware(request)

    assert status["state"] == "applied"
    stable_payload = "\n".join(
        str(m.content) for m in messages if isinstance(m, SystemMessage) and MEMORY_CONTEXT_MARKER in str(m.content)
    )
    assert "... (Some lower-priority memory items were truncated" in stable_payload
    assert "Use memory_search_tool to search for more" in stable_payload


@pytest.mark.asyncio
async def test_context_real_assembly_budget_truncation_notice_omits_tool(
    manager_factory: Callable[[RecallMode], MemoryManager],
) -> None:
    """CONTEXT truncation notice must not reference the unbound memory_search_tool."""
    manager = manager_factory(RecallMode.CONTEXT)
    store = manager._relational
    assert store is not None
    for i in range(80):
        await store.set_profile(f"k{i}", "w" * 300, scope=manager._scope)

    set_memory_manager(manager)
    request = _make_request(
        messages=[SystemMessage(content="sys prefix"), HumanMessage(content="hello")],
        tools=[],
    )

    messages, status = await _run_middleware(request)

    assert status["state"] == "applied"
    stable_payload = "\n".join(
        str(m.content) for m in messages if isinstance(m, SystemMessage) and MEMORY_CONTEXT_MARKER in str(m.content)
    )
    assert "... (Some lower-priority memory items were truncated" in stable_payload
    assert "memory_search_tool" not in stable_payload
    assert "Use memory_search_tool to search for more" not in stable_payload


@pytest.mark.asyncio
async def test_hybrid_real_assembly_is_idempotent(
    manager_factory: Callable[[RecallMode], MemoryManager],
    memory_search_tool: object,
) -> None:
    """Second turn (marker already present in state) must not inject again."""
    manager = manager_factory(RecallMode.HYBRID)
    await manager.set_profile_attribute("name", "Alice Real")

    set_memory_manager(manager)
    seeded = [
        SystemMessage(content="sys prefix"),
        SystemMessage(content="<user_memory_context>\nname: Alice Real\n</user_memory_context>"),
        HumanMessage(content="hello again"),
    ]
    request = _make_request(
        messages=[SystemMessage(content="sys prefix"), HumanMessage(content="hello again")],
        tools=[memory_search_tool],
        state_messages=list(seeded),
    )

    messages, status = await _run_middleware(request)

    assert status["state"] == "not_applied"
    assert status["reason"] == "already_present"
    # handler receives the untouched request: no extra memory block injected.
    assert all(
        isinstance(m, SystemMessage) is not True or MEMORY_CONTEXT_MARKER not in str(m.content)
        for m in messages
    )
    assert len([m for m in messages if isinstance(m, SystemMessage)]) == 1


# ---------------------------------------------------------------------------
# CONTEXT / TOOLS modes — no tool guidance, or no injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_context_real_assembly_injects_profile_without_guidance(
    manager_factory: Callable[[RecallMode], MemoryManager],
) -> None:
    """CONTEXT mode injects real profile but never references the unbound tool."""
    manager = manager_factory(RecallMode.CONTEXT)
    await manager.set_profile_attribute("name", "Carol Context")

    set_memory_manager(manager)
    request = _make_request(
        messages=[SystemMessage(content="sys prefix"), HumanMessage(content="hello")],
        tools=[],
    )

    messages, status = await _run_middleware(request)

    assert status["state"] == "applied"
    stable_msgs = [m for m in messages if isinstance(m, SystemMessage) and MEMORY_CONTEXT_MARKER in str(m.content)]
    assert len(stable_msgs) == 1
    stable = str(stable_msgs[0].content)
    assert "Carol Context" in stable
    assert "## Memory Search" not in stable
    assert "memory_search_tool" not in stable
    assert "## Citation Requirements" not in stable
    assert "<cite:MEMORY_ID>" not in stable


@pytest.mark.asyncio
async def test_context_real_assembly_cold_start_skips_injection(
    manager_factory: Callable[[RecallMode], MemoryManager],
) -> None:
    """CONTEXT cold-start (empty store, no tools) must not inject any block."""
    manager = manager_factory(RecallMode.CONTEXT)

    set_memory_manager(manager)
    request = _make_request(
        messages=[SystemMessage(content="sys prefix"), HumanMessage(content="hello")],
        tools=[],
    )

    messages, status = await _run_middleware(request)

    assert status["state"] == "not_applied"
    assert status["reason"] == "empty_context"
    assert all(
        isinstance(m, SystemMessage) is not True or MEMORY_CONTEXT_MARKER not in str(m.content)
        for m in messages
    )


@pytest.mark.asyncio
async def test_tools_recall_mode_real_assembly_skips(
    manager_factory: Callable[[RecallMode], MemoryManager],
    memory_search_tool: object,
) -> None:
    """RecallMode.TOOLS skips context injection entirely even with a real manager."""
    manager = manager_factory(RecallMode.TOOLS)
    await manager.set_profile_attribute("name", "Alice Real")

    set_memory_manager(manager)
    request = _make_request(
        messages=[SystemMessage(content="sys prefix"), HumanMessage(content="hello")],
        tools=[memory_search_tool],
    )

    messages, status = await _run_middleware(request)

    assert status["state"] == "not_applied"
    assert status["reason"] == "recall_mode_tools"
    assert all(
        isinstance(m, SystemMessage) is not True or MEMORY_CONTEXT_MARKER not in str(m.content)
        for m in messages
    )
