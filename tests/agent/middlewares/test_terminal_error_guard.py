"""Tests for non-recoverable (config/auth) terminal error early-stop.

Covers:
1. classify_terminal_error() pure classification logic (_tool_helpers) — family-scoped
2. handle_execution_error() registers terminal errors on config/auth failures
3. _check_circuit_breaker() blocks only same-family tools after config_or_auth registered
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.middlewares.tooling._tool_helpers import (
    TERMINAL_CONFIG_OR_AUTH,
    classify_terminal_error,
)
from myrm_agent_harness.toolkits.web_search.exceptions import (
    ErrorContext,
    SearchAPIError,
    SearchConfigError,
)

CONFIG_OR_AUTH_SEARCH = f"{TERMINAL_CONFIG_OR_AUTH}:search"
CONFIG_OR_AUTH_BROWSER = f"{TERMINAL_CONFIG_OR_AUTH}:browser"


# ---------------------------------------------------------------------------
# 1. classify_terminal_error pure function
# ---------------------------------------------------------------------------


class TestClassifyTerminalError:
    def test_search_config_error_classified_as_search_family(self) -> None:
        err = SearchConfigError("volcengine_doubao search requires API key configuration", config_key="api_key")
        assert classify_terminal_error(err) == CONFIG_OR_AUTH_SEARCH

    def test_search_api_401_classified_as_search_family(self) -> None:
        ctx = ErrorContext(query="hello", status_code=401, error_code="UNAUTHORIZED")
        err = SearchAPIError("Invalid API key", context=ctx)
        assert classify_terminal_error(err) == CONFIG_OR_AUTH_SEARCH

    def test_search_api_403_classified_as_search_family(self) -> None:
        ctx = ErrorContext(query="hello", status_code=403, error_code="FORBIDDEN")
        err = SearchAPIError("Access denied", context=ctx)
        assert classify_terminal_error(err) == CONFIG_OR_AUTH_SEARCH

    def test_search_api_retryable_status_not_classified(self) -> None:
        ctx = ErrorContext(query="hello", status_code=429, error_code="RATE_LIMITED", retryable=True)
        err = SearchAPIError("Rate limited", context=ctx)
        assert classify_terminal_error(err) is None

    def test_search_api_5xx_not_classified(self) -> None:
        ctx = ErrorContext(query="hello", status_code=500, error_code="INTERNAL")
        err = SearchAPIError("Provider internal error", context=ctx)
        assert classify_terminal_error(err) is None

    def test_search_api_no_status_not_classified(self) -> None:
        err = SearchAPIError("Search provider chain is empty")
        assert classify_terminal_error(err) is None

    def test_browser_launch_error_classified_as_browser_family(self) -> None:
        from myrm_agent_harness.toolkits.browser.exceptions import BrowserLaunchError

        err = BrowserLaunchError("Failed to launch browser: executable not found")
        assert classify_terminal_error(err) == CONFIG_OR_AUTH_BROWSER

    def test_browser_tool_config_error_not_classified(self) -> None:
        """ToolConfigurationError has no raise site in the codebase; treat as non-terminal."""
        from myrm_agent_harness.toolkits.browser.exceptions import ToolConfigurationError

        err = ToolConfigurationError("Invalid browser tool configuration")
        assert classify_terminal_error(err) is None

    def test_browser_navigation_error_not_classified(self) -> None:
        """Page-level failures (403/404/timeout) are site problems, not Myrm config."""
        from myrm_agent_harness.toolkits.browser.exceptions import BrowserNavigationError

        err = BrowserNavigationError(
            "Access forbidden",
            url="https://example.com/protected",
            status_code=403,
            error_text="HTTP 403",
        )
        assert classify_terminal_error(err) is None

    def test_browser_timeout_error_not_classified(self) -> None:
        from myrm_agent_harness.toolkits.browser.exceptions import BrowserTimeoutError

        err = BrowserTimeoutError("Timeout waiting for page load", operation="navigate")
        assert classify_terminal_error(err) is None

    def test_generic_exception_not_classified(self) -> None:
        assert classify_terminal_error(ValueError("boom")) is None

    def test_tool_error_not_classified(self) -> None:
        from myrm_agent_harness.utils.errors import ToolError

        err = ToolError(
            "Command failed",
            diagnostic_info={"error_category": "execution_failure"},
        )
        assert classify_terminal_error(err) is None


# ---------------------------------------------------------------------------
# 2. handle_execution_error registers terminal errors
# ---------------------------------------------------------------------------


class TestHandleExecutionErrorRegistersTerminalError:
    @pytest.mark.asyncio
    async def test_config_error_registers_family_tag(self) -> None:
        from myrm_agent_harness.agent.middlewares.tooling._tool_execution_lifecycle import (
            handle_execution_error,
        )

        terminal_errors: set[str] = set()
        err = SearchConfigError("search requires API key configuration", config_key="api_key")
        with (
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_terminal_errors",
                return_value=MagicMock(add=terminal_errors.add),
            ),
            patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._mutation_verifier.record_mutation_result"
            ),
        ):
            result = await handle_execution_error(err, "web_search_tool", "call_1", {"questions": ["x"]})

        assert CONFIG_OR_AUTH_SEARCH in terminal_errors
        assert isinstance(result, ToolMessage)
        assert result.status == "error"

    @pytest.mark.asyncio
    async def test_retryable_error_does_not_register(self) -> None:
        from myrm_agent_harness.agent.middlewares.tooling._tool_execution_lifecycle import (
            handle_execution_error,
        )

        terminal_errors: set[str] = set()
        err = ValueError("transient")
        with (
            patch(
                "myrm_agent_harness.agent.middlewares._session_context.get_terminal_errors",
                return_value=MagicMock(add=terminal_errors.add),
            ),
            patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock),
            patch(
                "myrm_agent_harness.agent.middlewares.tooling._mutation_verifier.record_mutation_result"
            ),
        ):
            result = await handle_execution_error(err, "web_search_tool", "call_2", {"questions": ["x"]})

        assert CONFIG_OR_AUTH_SEARCH not in terminal_errors
        assert isinstance(result, ToolMessage)


# ---------------------------------------------------------------------------
# 3. _check_circuit_breaker blocks only same-family tools
# ---------------------------------------------------------------------------


class TestCircuitBreakerConfigOrAuth:
    def test_search_family_blocks_search_tool(self) -> None:
        from myrm_agent_harness.agent.middlewares.tooling._tool_guards import (
            _check_circuit_breaker,
        )

        registry = MagicMock()
        registry._load = MagicMock()
        registry.get_all.return_value = {CONFIG_OR_AUTH_SEARCH}
        with patch(
            "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_terminal_errors",
            return_value=registry,
        ):
            result = _check_circuit_breaker("web_search_tool", "call_3")
        assert result is not None
        assert "circuit breaker" in result.content.lower()
        assert "Search is unavailable" in result.content
        assert "config_or_auth" not in result.content

    def test_search_family_does_not_block_browser_tool(self) -> None:
        """A broken search config must not disable browser tools (independent infra)."""
        from myrm_agent_harness.agent.middlewares.tooling._tool_guards import (
            _check_circuit_breaker,
        )

        registry = MagicMock()
        registry._load = MagicMock()
        registry.get_all.return_value = {CONFIG_OR_AUTH_SEARCH}
        with patch(
            "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_terminal_errors",
            return_value=registry,
        ):
            result = _check_circuit_breaker("browser_navigate", "call_4")
        assert result is None

    def test_browser_family_blocks_browser_tool(self) -> None:
        from myrm_agent_harness.agent.middlewares.tooling._tool_guards import (
            _check_circuit_breaker,
        )

        registry = MagicMock()
        registry._load = MagicMock()
        registry.get_all.return_value = {CONFIG_OR_AUTH_BROWSER}
        with patch(
            "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_terminal_errors",
            return_value=registry,
        ):
            result = _check_circuit_breaker("browser_navigate", "call_5")
        assert result is not None

    def test_browser_family_does_not_block_search_tool(self) -> None:
        """A broken browser environment must not disable search tools."""
        from myrm_agent_harness.agent.middlewares.tooling._tool_guards import (
            _check_circuit_breaker,
        )

        registry = MagicMock()
        registry._load = MagicMock()
        registry.get_all.return_value = {CONFIG_OR_AUTH_BROWSER}
        with patch(
            "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_terminal_errors",
            return_value=registry,
        ):
            result = _check_circuit_breaker("web_search_tool", "call_6")
        assert result is None

    def test_allows_non_network_tool(self) -> None:
        from myrm_agent_harness.agent.middlewares.tooling._tool_guards import (
            _check_circuit_breaker,
        )

        registry = MagicMock()
        registry._load = MagicMock()
        registry.get_all.return_value = {CONFIG_OR_AUTH_SEARCH}
        with patch(
            "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_terminal_errors",
            return_value=registry,
        ):
            result = _check_circuit_breaker("file_write", "call_7")
        assert result is None

    def test_allows_when_not_registered(self) -> None:
        from myrm_agent_harness.agent.middlewares.tooling._tool_guards import (
            _check_circuit_breaker,
        )

        registry = MagicMock()
        registry._load = MagicMock()
        registry.get_all.return_value = {}
        with patch(
            "myrm_agent_harness.agent.middlewares.tooling._tool_guards.get_terminal_errors",
            return_value=registry,
        ):
            result = _check_circuit_breaker("web_search_tool", "call_8")
        assert result is None
