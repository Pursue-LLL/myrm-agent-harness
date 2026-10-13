"""Stopping or tearing down a run while a browser tool is stuck, through the real agent chain.

A scripted model issues a real browser tool call (a navigation to a server that never answers, a
snapshot of a wedged renderer) inside a real LangGraph agent driven by the production
`StreamExecutor` with the production tool interceptor. Without the cancel boundary the stop flag is
never looked at and the run stays blocked; with it the run ends, the browser tab is healthy and
the model is not asked again. A run ended from outside (the executor's own timeout, the stuck-task
watchdog) must leave a healthy tab and a whole permit pool as well, and a Stop during the cold start
must not leak the permit it was acquiring.

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
from patchright.async_api import Page

from myrm_agent_harness.agent.middlewares.tooling import tool_executor
from myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware import tool_interceptor_middleware
from myrm_agent_harness.agent.streaming.stream_executor import STREAM_DONE, StreamContext, StreamExecutor
from myrm_agent_harness.agent.types import AgentRunStatistics
from myrm_agent_harness.toolkits.browser import domain_filter
from myrm_agent_harness.toolkits.browser.navigation import ssrf_guard
from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.pool.config import BrowserPoolConfig
from myrm_agent_harness.toolkits.browser.session import BrowserSession
from myrm_agent_harness.toolkits.browser.tools import create_browser_tools
from myrm_agent_harness.toolkits.browser.tools.navigate import create_navigate_tool
from myrm_agent_harness.toolkits.browser.utils.page_health import probe_alive
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
_PERMITS = 2
_TOOL_TIMEOUT_S = 3.0  # stands in for the executor's 120 s browser-tool timeout
_SPIN_SCRIPT = "() => { while (true) {} }"


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
    pool = GlobalBrowserPool(max_browsers=1, config=BrowserPoolConfig(max_concurrent_pages=_PERMITS))
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


@contextlib.asynccontextmanager
async def _wedged_renderer(session: BrowserSession) -> AsyncIterator[Page]:
    """Spin the active page's renderer, so every later driver call on it hangs."""
    page = session._tab_controller.get_active_page()
    spinner = asyncio.ensure_future(page.evaluate(_SPIN_SCRIPT))
    try:
        await asyncio.sleep(0.5)
        assert not await probe_alive(page), "the setup must really wedge the page"
        yield page
    finally:
        spinner.cancel()
        with contextlib.suppress(BaseException):
            await asyncio.wait_for(spinner, timeout=5.0)


def _recorded_snapshot_tool(session: BrowserSession) -> tuple[BaseTool, list[str]]:
    """The guarded snapshot tool plus every text result that actually reached the caller."""
    snapshot = next(t for t in create_browser_tools(session) if t.name == "browser_snapshot_tool")
    guarded = snapshot.coroutine
    delivered: list[str] = []

    async def record(*args: object, **kwargs: object) -> object:
        result = await guarded(*args, **kwargs)
        delivered.append(str(result))
        return result

    snapshot.coroutine = record
    return snapshot, delivered


async def test_stop_during_cold_start_returns_the_permit_it_was_acquiring(
    session: BrowserSession, servers: StallServers, monkeypatch: pytest.MonkeyPatch
) -> None:
    pool = session._browser_pool
    launched = asyncio.Event()
    real_create_context = pool._context_factory.create_context

    async def stall_after_launch(*args: object, **kwargs: object) -> object:
        launched.set()  # the browser is up; the context (and so the page) does not exist yet
        await asyncio.Event().wait()
        return await real_create_context(*args, **kwargs)

    monkeypatch.setattr(pool._context_factory, "create_context", stall_after_launch)
    run = _Run(create_browser_tools(session)[0], servers.ok, CancellationToken("e2e_cold_stop"))
    executing = run.start()
    await asyncio.wait_for(launched.wait(), timeout=60.0)

    run.token.cancel()
    await asyncio.wait_for(executing, timeout=30.0)

    assert run.stats.was_cancelled
    assert pool._global_semaphore._value == _PERMITS, "the half-finished acquisition kept its permit"
    set_cancel_token(None)
    monkeypatch.setattr(pool._context_factory, "create_context", real_create_context)
    assert "title=Good" in await asyncio.wait_for(session.navigate(servers.ok), timeout=30.0)


async def test_executor_timeout_heals_the_wedged_tab_and_the_retry_is_told_about_it(
    session: BrowserSession, servers: StallServers, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tool_executor, "get_tool_timeout", lambda *_args, **_kwargs: _TOOL_TIMEOUT_S)
    await session.new_tab()
    await session.navigate(servers.ok)
    snapshot_tool, delivered = _recorded_snapshot_tool(session)
    run = _Run(snapshot_tool, "ignored", CancellationToken("e2e_timeout"))

    async with _wedged_renderer(session) as wedged:
        await asyncio.wait_for(run.start(), timeout=90.0)
    set_cancel_token(None)

    assert wedged.is_closed(), "nobody pressed Stop; only the executor's timeout ended the call"
    assert await probe_alive(session._tab_controller.get_active_page())
    assert run.compactor.events[-1] is STREAM_DONE
    assert len(delivered) == 1, "the first attempt was torn down; only the retry delivered a result"
    assert "reset to a blank page" in delivered[0], "the retry must say why the page is blank"
    assert "title=Good" in await asyncio.wait_for(session.navigate(servers.ok), timeout=30.0)


async def test_watchdog_cancelling_token_and_task_together_leaves_a_healthy_tab(
    session: BrowserSession, servers: StallServers
) -> None:
    await session.new_tab()
    await session.navigate(servers.ok)
    snapshot_tool, _ = _recorded_snapshot_tool(session)
    run = _Run(snapshot_tool, "ignored", CancellationToken("e2e_watchdog"))

    async with _wedged_renderer(session) as wedged:
        executing = run.start()
        await asyncio.sleep(1.0)  # the snapshot call is now stuck in the driver
        run.token.cancel()
        executing.cancel()  # what the stuck-task watchdog does: flag and task in one breath
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(executing, timeout=30.0)
    set_cancel_token(None)

    assert wedged.is_closed()
    assert await probe_alive(session._tab_controller.get_active_page())
    assert session._browser_pool._global_semaphore._value == _PERMITS - 1, "exactly the one open tab holds a permit"
    assert "title=Good" in await asyncio.wait_for(session.navigate(servers.ok), timeout=30.0)
