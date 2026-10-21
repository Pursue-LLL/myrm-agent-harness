"""Cross-layer contract tests for the neutral ``core/`` primitives.

These lock the SSOT identity and ContextVar wiring that keep ``toolkits/`` free of
``agent/``/``backends/`` imports: a regression here would silently reintroduce a
forbidden dependency edge even while the boundary gate still passes.
"""

from __future__ import annotations

import myrm_agent_harness.api as api
from myrm_agent_harness.agent.middlewares._session_context import (
    get_approval_session,
    set_approval_session,
)
from myrm_agent_harness.agent.resilience import task_airbag
from myrm_agent_harness.agent.resilience.task_airbag import arm_task_airbag
from myrm_agent_harness.backends.skills.workflow_compiler import (
    DEFAULT_ALLOWED_TOOLS as COMPILER_DEFAULT_ALLOWED_TOOLS,
)
from myrm_agent_harness.core.context_vars import approval_session_var
from myrm_agent_harness.core.skill import DEFAULT_ALLOWED_TOOLS


def test_default_allowed_tools_is_the_shared_ssot() -> None:
    """The compiler re-exports the exact core object, not a divergent copy."""
    assert COMPILER_DEFAULT_ALLOWED_TOOLS is DEFAULT_ALLOWED_TOOLS
    assert api.DEFAULT_ALLOWED_TOOLS is DEFAULT_ALLOWED_TOOLS


def test_default_allowed_tools_entries_are_meaningful() -> None:
    assert isinstance(DEFAULT_ALLOWED_TOOLS, tuple)
    assert DEFAULT_ALLOWED_TOOLS, "the default allowed-tools allow-list must not be empty"
    assert all(isinstance(name, str) and name for name in DEFAULT_ALLOWED_TOOLS)


def test_task_airbag_is_reexported_from_api_security() -> None:
    """The agent-owned airbag is surfaced through the API facade unchanged."""
    from myrm_agent_harness.api.security import arm_task_airbag as api_arm_task_airbag

    assert api_arm_task_airbag is arm_task_airbag
    assert task_airbag.TaskAirbagStatus.ARMED.value == "armed"


def test_approval_session_var_is_the_cross_layer_source() -> None:
    """The core ContextVar and the agent accessor observe the same value."""
    assert approval_session_var.get() == ""
    token = approval_session_var.set("session-a")
    try:
        assert get_approval_session() == "session-a"
    finally:
        approval_session_var.reset(token)
    assert get_approval_session() == ""


def test_set_approval_session_updates_the_core_var() -> None:
    from myrm_agent_harness.core.context_vars import chat_id_var

    session_token = approval_session_var.set("")
    chat_token = chat_id_var.set("")
    try:
        set_approval_session("session-b")
        assert approval_session_var.get() == "session-b"
        assert chat_id_var.get() == "session-b"
    finally:
        chat_id_var.reset(chat_token)
        approval_session_var.reset(session_token)
    assert get_approval_session() == ""
    assert chat_id_var.get() == ""
