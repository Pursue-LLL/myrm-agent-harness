"""Cancel boundary: stopping a run releases a browser tool blocked in the driver, without changing the tool surface."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.tools import tool
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.errors import GraphInterrupt

from myrm_agent_harness.toolkits.browser.session.restricted_ax_session import create_restricted_ax_browser_tools
from myrm_agent_harness.toolkits.browser.tools import create_browser_tools
from myrm_agent_harness.toolkits.browser.tools.cancel_boundary import CANCELLED_RESULT, apply_cancel_boundary
from myrm_agent_harness.toolkits.browser.tools.execute_script import create_execute_script_tool
from myrm_agent_harness.toolkits.browser.tools.extract import create_extract_tool
from myrm_agent_harness.toolkits.browser.tools.inspect import create_inspect_tool
from myrm_agent_harness.toolkits.browser.tools.interact import create_interact_tool
from myrm_agent_harness.toolkits.browser.tools.manage import create_manage_tool
from myrm_agent_harness.toolkits.browser.tools.navigate import create_navigate_tool
from myrm_agent_harness.toolkits.browser.tools.snapshot import create_snapshot_tool
from myrm_agent_harness.toolkits.browser.tools.takeover import create_takeover_tool
from myrm_agent_harness.utils.runtime import cancellation
from myrm_agent_harness.utils.runtime.cancellation import CancellationToken, set_cancel_token

_BOUND_S = 3.0


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(cancellation, "_POLL_INTERVAL_S", 0.02)
    monkeypatch.setattr(cancellation, "_ABORT_GRACE_S", 0.2)
    yield
    set_cancel_token(None)


def _session() -> MagicMock:
    session = MagicMock()
    session.recover_active_tab = AsyncMock(return_value=None)
    session.take_tab_reset_notice = MagicMock(return_value=None)
    return session


def _hanging_tool(started: asyncio.Event, cancelled: asyncio.Event) -> StructuredTool:
    @tool("hang_tool")
    async def hang_tool(value: str) -> str:
        """Blocks like a driver call that never returns."""
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return value

    return hang_tool


async def _stop_when_started(token: CancellationToken, started: asyncio.Event) -> None:
    await asyncio.wait_for(started.wait(), timeout=_BOUND_S)
    token.cancel()


class TestStoppedRun:
    async def test_blocked_tool_is_aborted_healed_and_answered_with_a_plain_result(self) -> None:
        started, cancelled = asyncio.Event(), asyncio.Event()
        session = _session()
        (guarded,) = apply_cancel_boundary([_hanging_tool(started, cancelled)], session)
        token = CancellationToken("req")
        set_cancel_token(token)

        began = time.monotonic()
        stopper = asyncio.create_task(_stop_when_started(token, started))
        result = await asyncio.wait_for(guarded.ainvoke({"value": "x"}), timeout=_BOUND_S)
        await stopper

        assert result == CANCELLED_RESULT
        assert cancelled.is_set(), "the blocked call itself must be cancelled, not abandoned"
        session.recover_active_tab.assert_awaited_once()
        assert time.monotonic() - began < _BOUND_S

    async def test_real_navigate_tool_stuck_in_the_session_is_released(self) -> None:
        started, cancelled = asyncio.Event(), asyncio.Event()
        session = _session()

        async def stuck_navigate(*_args: object, **_kwargs: object) -> str:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return "unreachable"

        session.navigate = stuck_navigate
        (guarded,) = apply_cancel_boundary([create_navigate_tool(session)], session)
        token = CancellationToken("req")
        set_cancel_token(token)

        stopper = asyncio.create_task(_stop_when_started(token, started))
        result = await asyncio.wait_for(guarded.ainvoke({"url": "https://example.com"}), timeout=_BOUND_S)
        await stopper

        assert result == CANCELLED_RESULT
        assert cancelled.is_set()

    async def test_tool_started_after_the_stop_never_runs(self) -> None:
        started, cancelled = asyncio.Event(), asyncio.Event()
        session = _session()
        (guarded,) = apply_cancel_boundary([_hanging_tool(started, cancelled)], session)
        token = CancellationToken("req")
        token.cancel()
        set_cancel_token(token)

        assert await guarded.ainvoke({"value": "x"}) == CANCELLED_RESULT
        assert not started.is_set()


class TestNormalRun:
    async def test_without_a_token_the_tool_runs_untouched(self) -> None:
        session = _session()

        @tool("echo_tool")
        async def echo_tool(value: str) -> str:
            """Echo."""
            return f"echo:{value}"

        (guarded,) = apply_cancel_boundary([echo_tool], session)
        set_cancel_token(None)

        assert await guarded.ainvoke({"value": "a"}) == "echo:a"
        session.recover_active_tab.assert_not_awaited()

    async def test_with_a_live_token_the_result_is_unchanged(self) -> None:
        session = _session()

        @tool("echo_tool")
        async def echo_tool(value: str) -> str:
            """Echo."""
            return f"echo:{value}"

        (guarded,) = apply_cancel_boundary([echo_tool], session)
        set_cancel_token(CancellationToken("req"))

        assert await guarded.ainvoke({"value": "a"}) == "echo:a"
        session.recover_active_tab.assert_not_awaited()

    async def test_tool_errors_propagate_without_healing(self) -> None:
        session = _session()

        @tool("fail_tool")
        async def fail_tool(value: str) -> str:
            """Fails."""
            raise RuntimeError("boom")

        (guarded,) = apply_cancel_boundary([fail_tool], session)
        set_cancel_token(CancellationToken("req"))

        with pytest.raises(RuntimeError, match="boom"):
            await guarded.ainvoke({"value": "a"})
        session.recover_active_tab.assert_not_awaited()

    async def test_graph_interrupt_for_human_in_the_loop_passes_through(self) -> None:
        session = _session()

        @tool("hitl_tool")
        async def hitl_tool(value: str) -> str:
            """Pauses the graph for the user."""
            raise GraphInterrupt()

        (guarded,) = apply_cancel_boundary([hitl_tool], session)
        set_cancel_token(CancellationToken("req"))

        with pytest.raises(GraphInterrupt):
            await guarded.ainvoke({"value": "a"})

    async def test_injected_runnable_config_still_reaches_the_tool(self) -> None:
        session = _session()

        @tool("config_tool")
        async def config_tool(value: str, config: RunnableConfig) -> str:
            """Reads the injected config."""
            return f"{value}:{','.join(config.get('tags') or [])}"

        (guarded,) = apply_cancel_boundary([config_tool], session)
        set_cancel_token(CancellationToken("req"))

        assert await guarded.ainvoke({"value": "a"}, config={"tags": ["t1"]}) == "a:t1"


class TestRunTornDownFromOutside:
    """Executor timeout, stuck-task watchdog or shutdown cancel the tool without touching the token."""

    @staticmethod
    async def _cancelled_while_blocked(guarded: BaseTool, started: asyncio.Event) -> asyncio.Task[object]:
        set_cancel_token(CancellationToken("req"))  # alive: this is not a user stop
        running = asyncio.create_task(guarded.ainvoke({"value": "x"}))
        await asyncio.wait_for(started.wait(), timeout=_BOUND_S)
        return running

    async def test_tab_is_healed_before_the_cancellation_continues(self) -> None:
        started, cancelled = asyncio.Event(), asyncio.Event()
        session = _session()
        (guarded,) = apply_cancel_boundary([_hanging_tool(started, cancelled)], session)
        running = await self._cancelled_while_blocked(guarded, started)

        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(running, timeout=_BOUND_S)

        assert cancelled.is_set()
        session.recover_active_tab.assert_awaited_once()

    async def test_executor_style_timeout_still_ends_as_a_timeout_after_the_heal(self) -> None:
        started, cancelled = asyncio.Event(), asyncio.Event()
        session = _session()
        (guarded,) = apply_cancel_boundary([_hanging_tool(started, cancelled)], session)
        set_cancel_token(CancellationToken("req"))

        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.1):
                await guarded.ainvoke({"value": "x"})

        session.recover_active_tab.assert_awaited_once()

    async def test_a_second_cancellation_during_the_heal_still_propagates(self) -> None:
        started, cancelled = asyncio.Event(), asyncio.Event()
        healing = asyncio.Event()
        session = _session()

        async def slow_heal() -> None:
            healing.set()
            await asyncio.Event().wait()

        session.recover_active_tab = AsyncMock(side_effect=slow_heal)
        (guarded,) = apply_cancel_boundary([_hanging_tool(started, cancelled)], session)
        running = await self._cancelled_while_blocked(guarded, started)

        running.cancel()
        await asyncio.wait_for(healing.wait(), timeout=_BOUND_S)
        running.cancel()  # the watchdog cancelling the same task again
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(running, timeout=_BOUND_S)

    async def test_a_tool_failure_is_not_a_teardown_and_heals_nothing(self) -> None:
        session = _session()

        @tool("fail_tool")
        async def fail_tool(value: str) -> str:
            """Fails."""
            raise RuntimeError("boom")

        (guarded,) = apply_cancel_boundary([fail_tool], session)
        set_cancel_token(CancellationToken("req"))

        with pytest.raises(RuntimeError, match="boom"):
            await guarded.ainvoke({"value": "a"})

        session.recover_active_tab.assert_not_awaited()


class TestTabResetNotice:
    """A healed tab is blank, so the model must be told once, on the next text result."""

    @staticmethod
    def _echo_tool(result: object) -> StructuredTool:
        @tool("echo_tool")
        async def echo_tool(value: str) -> object:
            """Echo."""
            return result

        return echo_tool

    async def test_next_text_result_carries_the_notice_exactly_once(self) -> None:
        session = _session()
        session.take_tab_reset_notice.side_effect = ["The tab was reset.", None]
        (guarded,) = apply_cancel_boundary([self._echo_tool("page text")], session)
        set_cancel_token(CancellationToken("req"))

        assert await guarded.ainvoke({"value": "a"}) == "The tab was reset.\n\npage text"
        assert await guarded.ainvoke({"value": "a"}) == "page text"

    async def test_structured_result_is_left_untouched_and_the_notice_stays_pending(self) -> None:
        session = _session()
        session.take_tab_reset_notice.return_value = "The tab was reset."
        structured = {"url": "https://x.test/", "title": "t"}
        (guarded,) = apply_cancel_boundary([self._echo_tool(structured)], session)
        set_cancel_token(CancellationToken("req"))

        assert await guarded.ainvoke({"value": "a"}) == structured
        session.take_tab_reset_notice.assert_not_called()

    async def test_stopped_run_answer_does_not_consume_the_notice(self) -> None:
        started, cancelled = asyncio.Event(), asyncio.Event()
        session = _session()
        (guarded,) = apply_cancel_boundary([_hanging_tool(started, cancelled)], session)
        token = CancellationToken("req")
        set_cancel_token(token)
        stopper = asyncio.create_task(_stop_when_started(token, started))

        assert await asyncio.wait_for(guarded.ainvoke({"value": "x"}), timeout=_BOUND_S) == CANCELLED_RESULT
        await stopper

        session.take_tab_reset_notice.assert_not_called()


def test_a_tool_without_a_coroutine_is_rejected_instead_of_staying_uncancellable() -> None:
    sync_only = StructuredTool.from_function(func=lambda value: value, name="sync_tool", description="sync")

    with pytest.raises(TypeError, match="sync_tool"):
        apply_cancel_boundary([sync_only], _session())


class TestToolSurface:
    @staticmethod
    def _unguarded(session: MagicMock) -> list[BaseTool]:
        return [
            create_navigate_tool(session),
            create_inspect_tool(session),
            create_snapshot_tool(session),
            create_interact_tool(session),
            create_extract_tool(session),
            create_manage_tool(session),
            create_execute_script_tool(session),
            create_takeover_tool(session),
        ]

    @staticmethod
    def _surface(tool_: BaseTool) -> tuple[str, str, dict[str, object]]:
        return tool_.name, tool_.description, tool_.get_input_schema().model_json_schema()

    def test_every_browser_tool_is_guarded_and_the_model_visible_surface_is_unchanged(self) -> None:
        session = MagicMock()
        guarded = create_browser_tools(session)
        plain = self._unguarded(session)

        assert len(guarded) == len(plain) == 8
        for guarded_tool, plain_tool in zip(guarded, plain, strict=True):
            assert isinstance(guarded_tool, StructuredTool)
            assert hasattr(guarded_tool.coroutine, "__wrapped__"), guarded_tool.name
            assert self._surface(guarded_tool) == self._surface(plain_tool), guarded_tool.name

    def test_every_restricted_ax_tool_is_guarded(self) -> None:
        tools = create_restricted_ax_browser_tools(MagicMock())

        assert len(tools) == 7
        for tool_ in tools:
            assert isinstance(tool_, StructuredTool)
            assert hasattr(tool_.coroutine, "__wrapped__"), tool_.name

    def test_dynamic_hint_copies_keep_the_guarded_coroutine(self) -> None:
        navigate = create_browser_tools(MagicMock())[0]

        refreshed = navigate.dynamic_schema_modifier({"web_search_tool"})  # type: ignore[attr-defined]

        assert refreshed.coroutine is navigate.coroutine
        assert hasattr(refreshed.coroutine, "__wrapped__")
