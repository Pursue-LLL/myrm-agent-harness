"""Tests for register_ui_data_update (ui_registry)."""

from __future__ import annotations

from myrm_agent_harness.agent.artifacts.context import ArtifactContextManager
from myrm_agent_harness.agent.artifacts.ui_artifact import UIDataUpdate
from myrm_agent_harness.agent.artifacts.ui_registry import (
    bind_run_message_id,
    get_ui_registry,
    pop_pending_ui_events_for_message,
    pop_run_message_id,
    register_ui_data_update,
)


class TestRegisterUiDataUpdate:
    def test_register_with_active_registry(self) -> None:
        update = UIDataUpdate(surface_id="surface_a", updates={"status": "ok"})
        with ArtifactContextManager(message_id="msg_register_active"):
            assert register_ui_data_update(update) is True
            registry = get_ui_registry()
            assert registry is not None
            pending = pop_pending_ui_events_for_message("msg_register_active")
            assert len(pending) == 1
            assert pending[0] == update

    def test_register_fail_closed_without_context(self) -> None:
        update = UIDataUpdate(surface_id="ghost", updates={"k": "v"})
        assert register_ui_data_update(update) is False

    def test_register_stashes_when_no_registry_but_message_bound(self) -> None:
        session_key = "session_register_stash"
        message_id = "msg_register_stash"
        bind_run_message_id(session_key, message_id)
        try:
            update = UIDataUpdate(surface_id="surface_stash", updates={"k": "v"})
            assert register_ui_data_update(update) is True
            assert get_ui_registry() is None
            pending = pop_pending_ui_events_for_message(message_id)
            assert len(pending) == 1
            assert pending[0] == update
        finally:
            pop_run_message_id(session_key)
