"""Integration tests for the terminal error guard chain.

Verifies the full real path (no mocks on the guard chain itself):

1. A real ``SearchConfigError`` is classified into a family-scoped terminal
   category by ``classify_terminal_error`` (pure).
2. ``handle_execution_error`` registers the category in the real turn-scoped
   ``TerminalErrorRegistry`` (in-memory only — runtime state never touches the
   durable God-Mode file).
3. ``_check_circuit_breaker`` blocks same-family tools with a ``SYSTEM_ENFORCED``
   message while leaving independent-family tools untouched (search vs browser
   vs web_fetch isolation).
4. Legacy global categories (``any`` / ``network_blocked`` / ``sandbox_ro``)
   block tools with the expected scope (all / network-only / write-only).
5. The turn-scoped release: ``reset_terminal_errors`` clears the ContextVar
   runtime state so a new turn never inherits a previous turn's failure, while
   the durable God-Mode injection file survives and still blocks (the exact
   scenario the server e2e ``test_circuit_breaker_integration`` relies on).
6. Full real middleware assembly proves the same-family block in both the
   search and browser families after a real failure.
7. Regression on the browser wiring: a page-level ``BrowserNavigationError``
   is *not* classified as a Myrm config failure (browser navigation failures
   are site problems, not Myrm infrastructure).

[INPUT]
- agent.middlewares.tooling._tool_helpers::classify_terminal_error
- agent.middlewares.tooling._tool_execution_lifecycle::handle_execution_error
- agent.middlewares.tooling._tool_guards::_check_circuit_breaker
- agent.middlewares._session_context::reset_terminal_errors
- agent.security.terminal_error_registry::TerminalErrorRegistry

[OUTPUT]
- Integration tests proving the end-to-end guard chain with real I/O,
  including family isolation, legacy global categories, per-turn release,
  and the durable God-Mode injection channel.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.middlewares.tooling._tool_helpers import (
    TERMINAL_CONFIG_OR_AUTH,
    classify_terminal_error,
)
from myrm_agent_harness.agent.middlewares.tooling._tool_guards import (
    _check_circuit_breaker,
)
from myrm_agent_harness.agent.security.terminal_error_registry import (
    TerminalErrorRegistry,
)
from myrm_agent_harness.toolkits.web_search.exceptions import (
    ErrorContext,
    SearchAPIError,
    SearchConfigError,
)

CONFIG_OR_AUTH_SEARCH = f"{TERMINAL_CONFIG_OR_AUTH}:search"
CONFIG_OR_AUTH_BROWSER = f"{TERMINAL_CONFIG_OR_AUTH}:browser"

pytestmark = [pytest.mark.integration]


@pytest.fixture
def terminal_errors_path(tmp_path: Path) -> Path:
    """Point the real registry storage at a throw-away path and isolate state."""
    from myrm_agent_harness.agent.middlewares._session_context import (
        _terminal_errors_var,
        reset_terminal_errors,
    )

    reset_terminal_errors()
    storage = tmp_path / ".myrm_terminal_errors.json"
    with patch.dict("os.environ", {"MYRM_TERMINAL_ERRORS_PATH": str(storage)}, clear=False):
        # Force a fresh registry bound to the throw-away path so async tests do
        # not carry stale categories from a previous test's ContextVar instance.
        _terminal_errors_var.set(TerminalErrorRegistry(workspace_path=storage.parent))
        yield storage
        reset_terminal_errors()


def test_classify_real_search_config_error() -> None:
    """A real SearchConfigError is a family-scoped terminal category."""
    err = SearchConfigError("search requires API key configuration", config_key="api_key")
    assert classify_terminal_error(err) == CONFIG_OR_AUTH_SEARCH


def test_classify_real_search_api_401() -> None:
    """A 401 SearchAPIError is a family-scoped terminal category."""
    ctx = ErrorContext(query="q", status_code=401, error_code="UNAUTHORIZED")
    err = SearchAPIError("Invalid API key", context=ctx)
    assert classify_terminal_error(err) == CONFIG_OR_AUTH_SEARCH


def test_classify_browser_launch_is_browser_family() -> None:
    """A BrowserLaunchError maps to the browser family (independent of search)."""
    from myrm_agent_harness.toolkits.browser.exceptions import BrowserLaunchError

    err = BrowserLaunchError("Failed to launch browser: executable not found")
    assert classify_terminal_error(err) == CONFIG_OR_AUTH_BROWSER


def test_classify_browser_navigation_error_is_not_terminal() -> None:
    """Page-level navigation failures are site problems, never Myrm config."""
    from myrm_agent_harness.toolkits.browser.exceptions import BrowserNavigationError

    err = BrowserNavigationError(
        "HTTP 403",
        url="https://example.com/protected",
        status_code=403,
        error_text="Access forbidden",
    )
    assert classify_terminal_error(err) is None


def test_classify_real_search_api_403() -> None:
    """A 403 SearchAPIError is a family-scoped terminal category (unit parity)."""
    ctx = ErrorContext(query="q", status_code=403, error_code="FORBIDDEN")
    err = SearchAPIError("Access denied", context=ctx)
    assert classify_terminal_error(err) == CONFIG_OR_AUTH_SEARCH


@pytest.mark.asyncio
async def test_handle_execution_error_registers_turn_scoped_state(
    terminal_errors_path: Path,
) -> None:
    """handle_execution_error registers the category in the real turn-scoped registry."""
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_terminal_errors,
    )
    from myrm_agent_harness.agent.middlewares.tooling._tool_execution_lifecycle import (
        handle_execution_error,
    )

    err = SearchConfigError("search requires API key configuration", config_key="api_key")
    with (
        patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling._mutation_verifier.record_mutation_result"
        ),
    ):
        result = await handle_execution_error(err, "web_search_tool", "call_1", {"q": "x"})

    assert isinstance(result, ToolMessage)
    assert result.status == "error"

    # Runtime registration is turn-scoped (in-memory): the God-Mode file is not written.
    assert CONFIG_OR_AUTH_SEARCH in get_terminal_errors().get_all()
    assert not terminal_errors_path.exists()


@pytest.mark.asyncio
async def test_retryable_error_does_not_register(terminal_errors_path: Path) -> None:
    """A transient error must not poison the turn-scoped terminal registry."""
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_terminal_errors,
    )
    from myrm_agent_harness.agent.middlewares.tooling._tool_execution_lifecycle import (
        handle_execution_error,
    )

    err = ValueError("transient")
    with (
        patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock),
        patch(
            "myrm_agent_harness.agent.middlewares.tooling._mutation_verifier.record_mutation_result"
        ),
    ):
        await handle_execution_error(err, "web_search_tool", "call_2", {"q": "x"})

    assert get_terminal_errors().get_all() == set()


def test_circuit_breaker_blocks_same_family(terminal_errors_path: Path) -> None:
    """A turn-scoped search terminal tag blocks a search tool with SYSTEM_ENFORCED."""
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_terminal_errors,
    )

    get_terminal_errors().add(CONFIG_OR_AUTH_SEARCH)

    result = _check_circuit_breaker("web_search_tool", "call_3")
    assert result is not None
    assert "SYSTEM_ENFORCED" in result.content
    assert "Search is unavailable" in result.content
    assert result.additional_kwargs.get("error_category") == "circuit_breaker"


def test_circuit_breaker_allows_independent_family(terminal_errors_path: Path) -> None:
    """A broken search config must not disable browser tools (independent infra)."""
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_terminal_errors,
        reset_terminal_errors,
    )

    get_terminal_errors().add(CONFIG_OR_AUTH_SEARCH)

    result = _check_circuit_breaker("browser_navigate", "call_4")
    assert result is None

    # Sanity: the reverse direction (browser broken) does not block search tools.
    reset_terminal_errors()
    get_terminal_errors().add(CONFIG_OR_AUTH_BROWSER)
    search_result = _check_circuit_breaker("web_search_tool", "call_5")
    assert search_result is None


# ---------------------------------------------------------------------------
# Legacy global categories (any / network_blocked / sandbox_ro)
# ---------------------------------------------------------------------------


def test_circuit_breaker_any_blocks_every_tool(terminal_errors_path: Path) -> None:
    """'any' is a global kill switch: even a non-network tool is blocked."""
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_terminal_errors,
    )

    get_terminal_errors().add("any")

    for tool in ("web_search_tool", "browser_navigate_tool", "file_write"):
        result = _check_circuit_breaker(tool, "call_any")
        assert result is not None
        assert "SYSTEM_ENFORCED" in result.content


def test_circuit_breaker_network_blocked_blocks_network_allows_file(
    terminal_errors_path: Path,
) -> None:
    """network_blocked disables network tooling but leaves file I/O usable."""
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_terminal_errors,
    )

    get_terminal_errors().add("network_blocked")

    for tool in ("web_search_tool", "browser_navigate_tool", "web_fetch_tool"):
        assert _check_circuit_breaker(tool, "call_net") is not None

    assert _check_circuit_breaker("file_write", "call_fs") is None


def test_circuit_breaker_sandbox_ro_blocks_write_allows_network(
    terminal_errors_path: Path,
) -> None:
    """sandbox_ro disables write tools but leaves read/network tools usable."""
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_terminal_errors,
    )

    get_terminal_errors().add("sandbox_ro")

    for tool in ("file_write", "file_edit"):
        assert _check_circuit_breaker(tool, "call_write") is not None

    assert _check_circuit_breaker("web_search_tool", "call_net") is None
    assert _check_circuit_breaker("file_read", "call_read") is None


def test_config_or_auth_search_does_not_block_web_fetch(terminal_errors_path: Path) -> None:
    """web_fetch is independent infrastructure: a broken search config must not disable it."""
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_terminal_errors,
    )

    get_terminal_errors().add(CONFIG_OR_AUTH_SEARCH)

    assert _check_circuit_breaker("web_fetch_tool", "call_fetch") is None


# ---------------------------------------------------------------------------
# Turn-scoped release + durable God-Mode injection
# ---------------------------------------------------------------------------


def test_reset_terminal_errors_releases_circuit_breaker(terminal_errors_path: Path) -> None:
    """Runtime state is turn-scoped: reset clears the in-memory set so a new turn
    is never blocked by a previous turn's runtime failure."""
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_terminal_errors,
        reset_terminal_errors,
    )

    get_terminal_errors().add(CONFIG_OR_AUTH_SEARCH)
    assert CONFIG_OR_AUTH_SEARCH in get_terminal_errors().get_all()

    reset_terminal_errors()

    assert _check_circuit_breaker("web_search_tool", "call_after_reset") is None


def test_god_mode_file_injection_survives_reset_and_blocks(
    terminal_errors_path: Path,
) -> None:
    """The God-Mode injection channel is durable: an operator-written file must
    take effect even after reset_terminal_errors clears the turn-scoped memory.
    This is the exact scenario the server e2e (test_circuit_breaker_integration)
    relies on."""
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_terminal_errors,
        reset_terminal_errors,
    )

    terminal_errors_path.write_text('["network_blocked"]', encoding="utf-8")

    reset_terminal_errors()

    # The injected category survives the reset via the durable file channel.
    assert "network_blocked" in get_terminal_errors().get_all()
    result = _check_circuit_breaker("web_search_tool", "call_god_mode")
    assert result is not None
    assert "SYSTEM_ENFORCED" in result.content


# ---------------------------------------------------------------------------
# Full middleware assembly (real pre-guard chain, no guard mocks)
# ---------------------------------------------------------------------------


def _make_request(tool_name: str, call_id: str):
    """Build a a minimal ToolCallRequest for the real middleware entry."""
    from langgraph.prebuilt.tool_node import ToolCallRequest
    from unittest.mock import MagicMock

    return ToolCallRequest(
        tool_call={"name": tool_name, "id": call_id, "args": {}},
        tool=MagicMock(),
        state=None,
        runtime=MagicMock(),
    )


@pytest.mark.asyncio
async def test_full_middleware_chain_blocks_same_family_after_real_failure(
    terminal_errors_path: Path,
) -> None:
    """Real middleware: a search failure registers a terminal tag, and the next
    same-family call in the same turn is blocked by the real circuit breaker."""
    from myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware import (
        _tool_interceptor_middleware_inner,
    )

    async def failing_handler(_req) -> ToolMessage:
        raise SearchConfigError("search requires API key configuration", config_key="api_key")

    # First call: the search tool fails with a terminal error.
    first = await _tool_interceptor_middleware_inner(
        _make_request("web_search_tool", "call_fail"),
        failing_handler,
    )
    assert first.status == "error"

    # The turn-scoped registry holds the family tag (in-memory, no file write).
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_terminal_errors,
    )

    assert CONFIG_OR_AUTH_SEARCH in get_terminal_errors().get_all()
    assert not terminal_errors_path.exists()

    # Second same-family call in the same turn: circuit breaker blocks it.
    ok = False

    async def succeeding_handler(_req) -> ToolMessage:
        nonlocal ok
        ok = True
        return ToolMessage(content="unexpected", name="web_search_tool", tool_call_id="call_2")

    second = await _tool_interceptor_middleware_inner(
        _make_request("web_search_tool", "call_2"),
        succeeding_handler,
    )
    assert second.status == "error"
    assert "SYSTEM_ENFORCED" in second.content
    assert not ok, "the real circuit breaker must not delegate to the handler"

    # An independent-family tool is still allowed through to the handler.
    allowed = await _tool_interceptor_middleware_inner(
        _make_request("browser_navigate", "call_3"),
        succeeding_handler,
    )
    assert "unexpected" in allowed.content
    assert ok


@pytest.mark.asyncio
async def test_full_middleware_chain_retryable_error_is_not_blocked(
    terminal_errors_path: Path,
) -> None:
    """A transient error must not poison the breaker for later calls."""
    from myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware import (
        _tool_interceptor_middleware_inner,
    )

    async def transient_handler(_req) -> ToolMessage:
        raise ValueError("transient")

    first = await _tool_interceptor_middleware_inner(
        _make_request("web_search_tool", "call_fail"),
        transient_handler,
    )
    assert first.status == "error"
    from myrm_agent_harness.agent.middlewares._session_context import (
        get_terminal_errors,
    )

    assert get_terminal_errors().get_all() == set()

    ok = False

    async def succeeding_handler(_req) -> ToolMessage:
        nonlocal ok
        ok = True
        return ToolMessage(content="ok", name="web_search_tool", tool_call_id="call_2")

    second = await _tool_interceptor_middleware_inner(
        _make_request("web_search_tool", "call_2"),
        succeeding_handler,
    )
    assert "ok" in second.content
    assert "SYSTEM_ENFORCED" not in second.content
    assert ok


@pytest.mark.asyncio
async def test_full_middleware_chain_browser_family_blocked_after_launch_failure(
    terminal_errors_path: Path,
) -> None:
    """Real middleware: a BrowserLaunchError registers the browser family, the next
    browser call is blocked SYSTEM_ENFORCED, and search stays available."""
    from myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware import (
        _tool_interceptor_middleware_inner,
    )
    from myrm_agent_harness.toolkits.browser.exceptions import BrowserLaunchError

    async def failing_handler(_req) -> ToolMessage:
        raise BrowserLaunchError("Failed to launch browser: executable not found")

    first = await _tool_interceptor_middleware_inner(
        _make_request("browser_navigate_tool", "call_launch_fail"),
        failing_handler,
    )
    assert first.status == "error"

    from myrm_agent_harness.agent.middlewares._session_context import (
        get_terminal_errors,
    )

    assert CONFIG_OR_AUTH_BROWSER in get_terminal_errors().get_all()

    ok = False

    async def succeeding_handler(_req) -> ToolMessage:
        nonlocal ok
        ok = True
        return ToolMessage(content="browser-ok", name="browser_navigate_tool", tool_call_id="call_b2")

    second = await _tool_interceptor_middleware_inner(
        _make_request("browser_navigate_tool", "call_b2"),
        succeeding_handler,
    )
    assert second.status == "error"
    assert "SYSTEM_ENFORCED" in second.content
    assert not ok, "the browser family circuit breaker must not delegate to the handler"

    search_allowed = await _tool_interceptor_middleware_inner(
        _make_request("web_search_tool", "call_s2"),
        succeeding_handler,
    )
    assert "browser-ok" in search_allowed.content
    assert ok