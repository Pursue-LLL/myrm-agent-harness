"""CI negative regression gate: Tool exception traceback & secret redaction.

Hermes #32 / Red Team #77484 regression gate:
Asserts that all error propagation paths (tool exceptions, tracebacks,
stderr, execution errors, and background process listings) do not
silently leak secrets/credentials (sk-proj-..., ghp_..., xoxb-..., etc.).
"""

from __future__ import annotations

import traceback
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import ToolMessage

from myrm_agent_harness.agent.meta_tools.bash._background.registry import (
    BackgroundProcessRegistry,
)
from myrm_agent_harness.agent.meta_tools.bash._executor.error import BashExecutionError
from myrm_agent_harness.agent.middlewares.tooling._tool_helpers import format_tool_error
from myrm_agent_harness.agent.middlewares.tooling.tool_executor import execute_with_retry
from myrm_agent_harness.toolkits.code_execution.executors.models import (
    AsyncProcessProtocol,
)
from myrm_agent_harness.utils.errors import ToolError, format_error_message

_TEST_SECRET_OPENAI = "sk-proj-1234567890abcdef1234567890abcdef"
_TEST_SECRET_ANTHROPIC = "sk-ant-api03-abcdefghijklmnop1234567890"
_TEST_SECRET_GITHUB = "ghp_abcdefghijklmnop1234567890123456"
_TEST_SECRET_SLACK = "xoxb-TESTING_MOCK_TOKEN_NOT_REAL_SECRET_123"


class _DummyProc:
    def __init__(self, pid: int = 99123) -> None:
        self._proc = MagicMock()
        self._proc.pid = pid
        self.stdout = None
        self.stderr = None

    async def wait(self) -> int:
        return 0


def test_tool_error_format_for_llm_redacts_credentials() -> None:
    """ToolError.format_for_llm and initialization must redact all secrets."""
    err = ToolError(
        message=f"Request failed with key: {_TEST_SECRET_OPENAI}",
        user_hint=f"Check your PAT: {_TEST_SECRET_GITHUB}",
        diagnostic_info={
            "auth": f"Bearer {_TEST_SECRET_ANTHROPIC}",
            "status": 401,
        },
        recovery_suggestions=[
            f"Rotate token {_TEST_SECRET_SLACK} immediately",
        ],
        error_code="AUTH_FAILURE",
    )

    # 1. str(err) defense
    err_str = str(err)
    assert _TEST_SECRET_OPENAI not in err_str
    assert "sk-proj-" not in err_str

    # 2. hint property defense
    assert _TEST_SECRET_GITHUB not in err.user_hint
    assert "ghp_abcdefghijklmnop" not in err.user_hint
    assert "..." in err.user_hint or "***" in err.user_hint

    # 3. format_for_llm output
    llm_text = err.format_for_llm()
    assert _TEST_SECRET_OPENAI not in llm_text
    assert _TEST_SECRET_GITHUB not in llm_text
    assert _TEST_SECRET_ANTHROPIC not in llm_text
    assert _TEST_SECRET_SLACK not in llm_text


def test_format_error_message_with_traceback_redacts_frame_secrets() -> None:
    """format_error_message with include_traceback=True must redact secrets in traceback."""
    def _inner_failing_call() -> None:
        secret_var = _TEST_SECRET_OPENAI
        raise ValueError(f"Invalid secret in frame: {secret_var}")

    try:
        _inner_failing_call()
    except ValueError as exc:
        formatted = format_error_message(
            exc,
            context=f"Context with Authorization: Bearer {_TEST_SECRET_ANTHROPIC}",
            include_traceback=True,
        )

        assert _TEST_SECRET_OPENAI not in formatted
        assert _TEST_SECRET_ANTHROPIC not in formatted
        assert "Stack trace:" in formatted


def test_bash_execution_error_redacts_credentials() -> None:
    """BashExecutionError message and error_hint must be sanitized at construction."""
    err = BashExecutionError(
        message=f"Command exit 1: curl -H 'Authorization: Bearer {_TEST_SECRET_OPENAI}'",
        error_hint=f"Verify your Slack token {_TEST_SECRET_SLACK}",
        error_category="network_error",
    )

    err_str = str(err)
    assert _TEST_SECRET_OPENAI not in err_str
    assert err.error_hint is not None
    assert _TEST_SECRET_SLACK not in err.error_hint


def test_middleware_format_tool_error_redacts_arbitrary_exception() -> None:
    """format_tool_error must sanitize arbitrary third-party exceptions."""
    raw_exc = RuntimeError(f"HTTP request failed: https://api.example.com?api_key={_TEST_SECRET_OPENAI}")
    formatted = format_tool_error(raw_exc, "mcp_search_tool")

    assert _TEST_SECRET_OPENAI not in formatted
    assert "sk-proj-" not in formatted
    assert "mcp_search_tool execution failed" in formatted


@pytest.mark.asyncio
async def test_tool_execution_middleware_pipeline_redaction() -> None:
    """End-to-end execute_with_retry returns ToolMessage with redacted content."""
    req = MagicMock()
    req.tool_call = {"name": "code_execution_tool", "id": "tc_test_redaction"}

    async def _failing_handler(call_req: object = None, **kwargs: object) -> str:
        raise RuntimeError(f"Sandbox runner crashed with token {_TEST_SECRET_GITHUB}")

    with (
        patch("myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_event_logger", return_value=None),
        patch("myrm_agent_harness.agent.middlewares.tooling.tool_executor.get_terminal_errors", return_value=set()),
    ):
        try:
            tool_msg = await execute_with_retry(
                req,
                _failing_handler,
                "code_execution_tool",
                "tc_test_redaction",
                allowed_domains=None,
            )
        except Exception as exc:
            # Emulate tool_interceptor_middleware / runner wrapping
            tool_msg = ToolMessage(
                content=format_tool_error(exc, "code_execution_tool"),
                name="code_execution_tool",
                tool_call_id="tc_test_redaction",
                status="error",
            )
            if isinstance(exc, ToolError):
                orig_err = str(exc.diagnostic_info.get("original_error", ""))
                assert _TEST_SECRET_GITHUB not in orig_err
                assert "ghp_abcdefghijklmnop" not in orig_err

    assert isinstance(tool_msg, ToolMessage)
    content_str = str(tool_msg.content)
    assert _TEST_SECRET_GITHUB not in content_str
    assert "ghp_abcdefghijklmnop" not in content_str
    assert "..." in content_str or "***" in content_str


@pytest.mark.asyncio
async def test_background_process_registry_and_list_redaction_regression() -> None:
    """BackgroundProcessRegistry register and list_processes must redact commands."""
    registry = BackgroundProcessRegistry()
    dummy_proc = _DummyProc(pid=88421)

    cmd_with_secrets = f"export API_KEY={_TEST_SECRET_ANTHROPIC} && run --secret {_TEST_SECRET_OPENAI}"
    info = await registry.register(
        cast(AsyncProcessProtocol, dummy_proc),
        command=cmd_with_secrets,
        session_id="regression-sess-1",
    )

    # 1. info snapshot
    assert _TEST_SECRET_ANTHROPIC not in info.command
    assert _TEST_SECRET_OPENAI not in info.command

    # 2. to_dict() serialization
    as_dict = info.to_dict()
    cmd_in_dict = str(as_dict["command"])
    assert _TEST_SECRET_ANTHROPIC not in cmd_in_dict
    assert _TEST_SECRET_OPENAI not in cmd_in_dict

    # 3. list_processes() listing
    processes = registry.list_processes(session_id="regression-sess-1")
    assert len(processes) >= 1
    target = next((p for p in processes if p.pid == 88421), None)
    assert target is not None
    assert _TEST_SECRET_ANTHROPIC not in target.command
    assert _TEST_SECRET_OPENAI not in target.command
