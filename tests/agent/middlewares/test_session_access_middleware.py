"""Tests for SessionAccessMiddleware.

Validates directory-access injection: when a security config is present the
middleware appends a session-access SystemMessage exactly once, and safely
no-ops for missing config / non-list messages / already-injected markers.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import HumanMessage, SystemMessage

from myrm_agent_harness.agent.middlewares.session_access_middleware import (
    _SESSION_ACCESS_MARKER,
    SessionAccessMiddleware,
)
from myrm_agent_harness.agent.security.types import PathPolicy


def _make_config() -> object:
    """Build a security config object exposing `.path_policy` (the PathPolicy)."""
    return SimpleNamespace(path_policy=PathPolicy(access_roots=[]))


class TestBeforeModel:
    def test_no_config_returns_none(self) -> None:
        mw = SessionAccessMiddleware()
        with patch(
            "myrm_agent_harness.agent.middlewares.session_access_middleware.get_security_config",
            return_value=None,
        ):
            assert mw.before_model({"messages": []}, None) is None

    def test_empty_block_returns_none(self) -> None:
        mw = SessionAccessMiddleware()
        with (
            patch(
                "myrm_agent_harness.agent.middlewares.session_access_middleware.get_security_config",
                return_value=_make_config(),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.session_access_middleware.get_workspace_root",
                return_value="",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.session_access_middleware.render_session_access_context",
                return_value="",
            ),
        ):
            assert mw.before_model({"messages": []}, None) is None

    def test_non_list_messages_returns_none(self) -> None:
        mw = SessionAccessMiddleware()
        with (
            patch(
                "myrm_agent_harness.agent.middlewares.session_access_middleware.get_security_config",
                return_value=_make_config(),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.session_access_middleware.get_workspace_root",
                return_value="/ws",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.session_access_middleware.render_session_access_context",
                return_value="Available directories...",
            ),
        ):
            assert mw.before_model({"messages": "not-a-list"}, None) is None

    def test_injects_system_message_once(self) -> None:
        mw = SessionAccessMiddleware()
        with (
            patch(
                "myrm_agent_harness.agent.middlewares.session_access_middleware.get_security_config",
                return_value=_make_config(),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.session_access_middleware.get_workspace_root",
                return_value="/ws",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.session_access_middleware.render_session_access_context",
                return_value="- /ws [read-write]",
            ),
        ):
            result = mw.before_model({"messages": [HumanMessage(content="hi")]}, None)
            assert result is not None
            messages = result["messages"]
            assert len(messages) == 2
            assert isinstance(messages[-1], SystemMessage)
            assert _SESSION_ACCESS_MARKER in messages[-1].content
            assert "</session-access>" in messages[-1].content

    def test_skips_when_marker_already_present(self) -> None:
        mw = SessionAccessMiddleware()
        existing = SystemMessage(content=f"{_SESSION_ACCESS_MARKER}\nblock")
        with (
            patch(
                "myrm_agent_harness.agent.middlewares.session_access_middleware.get_security_config",
                return_value=_make_config(),
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.session_access_middleware.get_workspace_root",
                return_value="/ws",
            ),
            patch(
                "myrm_agent_harness.agent.middlewares.session_access_middleware.render_session_access_context",
                return_value="- /ws [read-write]",
            ),
        ):
            result = mw.before_model(
                {"messages": [HumanMessage(content="hi"), existing]}, None
            )
            assert result is None

    def test_after_model_returns_none(self) -> None:
        mw = SessionAccessMiddleware()
        assert mw.after_model({"messages": []}, None) is None
