"""Stopping a run while a browser tool is stuck in the driver, through the real agent chain.

A scripted model issues a real `browser_navigate_tool` call against a server that never answers,
inside a real LangGraph agent driven by the production `StreamExecutor` with the production tool
interceptor. Without the cancel boundary the stop flag is never looked at and the run stays blocked;
with it the run ends, the browser tab is healthy and the model is not asked again.

Run with: `pytest -m integration tests/agent/streaming/test_stop_during_browser_tool_e2e.py`.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator, Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import BaseTool

from myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware import tool_interceptor_middleware
from myrm_agent_harness.agent.streaming.stream_executor import STREAM_DONE, StreamContext, StreamExecutor
from myrm_agent_harness.agent.types import AgentRunStatistics
from myrm_agent_harness.toolkits.browser import domain_filter
from myrm_agent_harness.toolkits.browser.navigation import ssrf_guard
from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession
from myrm_agent_harness.toolkits.browser.tools import create_browser_tools
from myrm_agent_harness.toolkits.browser.tools.navigate import create_navigate_tool
from myrm_agent_harness.utils.runtime.cancellation import CancellationToken, set_cancel_token
from tests.toolkits.browser._browser_available import chromium_available
from tests.toolkits.browser._stall_servers import StallServers

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.skipif(not chromium_available(), reason="Chromium not available"),
]

_STOP_BOUND_S = 8.0  # well under the 15 s navigation timeout, which is when an unguarded run would end
_CONTROL_WAIT_S = 4.0
_TEARDOWN_BOUND_S = 20.0


class _ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: object, **kwargs: object) -> _ScriptedModel:
        return self


class _FakeCompactor:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def put(self, event: object) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _loopback_servers_are_reachable(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    original = domain_filter._install_http_filter

    async def allow_private(context, allowlist, resource_block, ad_blocklist, domain_blocklist, **_kwargs):
        return await original(
            context, allowlist, resource_block, ad_blocklist, domain_blocklist, allow_private_networks=True
        )

    monkeypatch.setattr(domain_filter, "_install_http_filter", allow_private)
    monkeypatch.setattr(ssrf_guard, "assert_browser_navigation_allowed", AsyncMock(return_value=None))
    yield
    set_cancel_token(None)


@pytest.fixture
async def servers() -> AsyncIterator[StallServers]:
    async with StallServers() as running:
        yield running


@pytest.fixture
async def session() -> AsyncIterator[BrowserSession]:
    pool = GlobalBrowserPool(max_browsers=1)
    browser_session = BrowserSession(pool, ContextType.AGENT, allow_private_networks=True)
    yield browser_session
    with contextlib.suppress(Exception):
        await asyncio.wait_for(browser_session.close(), timeout=_TEARDOWN_BOUND_S)
    with contextlib.suppress(Exception):
        await asyncio.wait_for(pool.shutdown(), timeout=_TEARDOWN_BOUND_S)


class _Run:
    """One scripted agent run executing under the production StreamExecutor."""

    def __init__(self, navigate_tool: BaseTool, url: str, token: CancellationToken) -> None:
        self.token = token
        self.model = _ScriptedModel(
            responses=[
                AIMessage(content="", tool_calls=[{"name": navigate_tool.name, "args": {"url": url}, "id": "call_1"}]),
                AIMessage(content="finished"),
            ]
        )
        agent = create_agent(self.model, tools=[navigate_tool], middleware=[tool_interceptor_middleware])
        self.stats = AgentRunStatistics()
        self.ctx = StreamContext(
            agent=agent,
            agent_input={"messages": [HumanMessage(content="open the page")]},
            merged_context={"locale": "en"},
            run_config={},
            stats=self.stats,
            message_id="e2e_stop",
            cancel_token=token,
            steering_token=None,
            source_tracker=MagicMock(),
            output_queue=asyncio.Queue(),
        )
        self.executor = StreamExecutor(
            ctx=self.ctx, fallback_llm=None, safety_fallback_llm=None, rebuild_agent_fn=MagicMock()
        )
        self.compactor = _FakeCompactor()
        self.executor._compactor = self.compactor

    def start(self) -> asyncio.Task[None]:
        set_cancel_token(self.token)  # as the agent runtime does before it spawns the executor task
        return asyncio.create_task(self.executor.execute())


async def test_stop_ends_the_run_heals_the_tab_and_the_model_is_not_asked_again(
    session: BrowserSession, servers: StallServers
) -> None:
    navigate_tool = create_browser_tools(session)[0]
    await session.new_tab()
    run = _Run(navigate_tool, servers.silent, CancellationToken("e2e_stop"))
    executing = run.start()
    await servers.wait_for_request(servers.silent)  # the navigation is now stuck inside the driver

    stopped = time.monotonic()
    run.token.cancel()
    await asyncio.wait_for(executing, timeout=30.0)

    assert time.monotonic() - stopped < _STOP_BOUND_S
    assert any(getattr(event, "type", None) == "tool_start" for event in run.compactor.events), "the tool really ran"
    assert run.stats.was_cancelled
    assert run.compactor.events[-1] is STREAM_DONE
    assert run.model.i == 1, "no further model request may follow the stop"
    set_cancel_token(None)
    assert "title=Good" in await asyncio.wait_for(session.navigate(servers.ok), timeout=30.0)


async def test_control_without_the_boundary_the_stopped_run_stays_blocked(
    session: BrowserSession, servers: StallServers
) -> None:
    unguarded_navigate = create_navigate_tool(session)
    await session.new_tab()
    run = _Run(unguarded_navigate, servers.silent, CancellationToken("e2e_stop_control"))
    executing = run.start()
    await servers.wait_for_request(servers.silent)

    run.token.cancel()
    await asyncio.sleep(_CONTROL_WAIT_S)

    try:
        assert not executing.done(), "the flag alone releases nothing: this is the defect the boundary removes"
    finally:
        executing.cancel()
        with contextlib.suppress(BaseException):
            await asyncio.wait_for(executing, timeout=10.0)
