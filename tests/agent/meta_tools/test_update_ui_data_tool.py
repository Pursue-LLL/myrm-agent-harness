"""Tests for update_ui_data_tool."""

from __future__ import annotations

import pytest

import myrm_agent_harness.agent.artifacts.ui_registry as _ui_reg_mod
from myrm_agent_harness.agent.artifacts.context import ArtifactContextManager
from myrm_agent_harness.agent.artifacts.ui_artifact import UIArtifact, UIDataUpdate
from myrm_agent_harness.agent.artifacts.ui_registry import (
    _PENDING_BY_MESSAGE_ID,
    _RUN_MESSAGE_ID_BY_SESSION,
    pop_pending_ui_events_for_message,
)
from myrm_agent_harness.agent.meta_tools.interaction.render_ui_tool import render_ui
from myrm_agent_harness.agent.meta_tools.interaction.update_ui_data_tool import update_ui_data


@pytest.fixture(autouse=True)
def _clean_ui_globals(monkeypatch):
    """Prevent cross-test pollution from global UI registry state."""
    _RUN_MESSAGE_ID_BY_SESSION.clear()
    _PENDING_BY_MESSAGE_ID.clear()
    monkeypatch.setattr(_ui_reg_mod, "_CURRENT_RUN_UI_MESSAGE_ID", None)
    from myrm_agent_harness.agent.middlewares._session_context import _active_message_id_var
    from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
        _current_message_id as _snapshot_msg_id_var,
    )
    _active_message_id_var.set(None)
    _snapshot_msg_id_var.set(None)
    yield
    _RUN_MESSAGE_ID_BY_SESSION.clear()
    _PENDING_BY_MESSAGE_ID.clear()
    _active_message_id_var.set(None)
    _snapshot_msg_id_var.set(None)


class TestUpdateUiDataTool:
    def test_update_ui_data_registers_patch(self) -> None:
        message_id = "msg_update_ui_data"
        with ArtifactContextManager(message_id=message_id):
            render_ui(
                title="Status board",
                components=[{"id": "t1", "type": "text", "props": {"text": "loading"}}],
                root_ids=["t1"],
                data={"status": {"label": "pending"}},
            )
            pending = pop_pending_ui_events_for_message(message_id)
            assert len(pending) == 1
            artifact = pending[0]
            assert isinstance(artifact, UIArtifact)

            result = update_ui_data(artifact.surface_id, {"status": {"label": "ready"}})
            assert "surface_id=" in result

            updates_pending = pop_pending_ui_events_for_message(message_id)
            assert len(updates_pending) == 1
            update = updates_pending[0]
            assert isinstance(update, UIDataUpdate)
            assert update.surface_id == artifact.surface_id
            assert update.updates == {"status": {"label": "ready"}}

    def test_update_ui_data_fail_closed_without_context(self) -> None:
        result = update_ui_data("ghost_surface", {"k": "v"})
        assert "Failed to update UI data" in result

    def test_update_ui_data_rejects_empty_surface_id(self) -> None:
        with ArtifactContextManager(message_id="msg_empty_surface"):
            result = update_ui_data("   ", {"k": "v"})
            assert "surface_id must not be empty" in result

    def test_update_ui_data_rejects_empty_updates(self) -> None:
        message_id = "msg_empty_updates"
        with ArtifactContextManager(message_id=message_id):
            render_ui(
                title="Board",
                components=[{"id": "t1", "type": "text", "props": {"text": "x"}}],
                root_ids=["t1"],
            )
            pending = pop_pending_ui_events_for_message(message_id)
            surface_id = pending[0].surface_id

            result = update_ui_data(surface_id, {})
            assert "updates must not be empty" in result
