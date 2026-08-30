"""Tests for A2UI spec helpers and render_ui fail-closed validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import tiktoken

import myrm_agent_harness.agent.artifacts.ui_registry as _ui_reg_mod
from myrm_agent_harness.agent.artifacts.context import ArtifactContextManager
from myrm_agent_harness.agent.artifacts.ui_artifact import UIComponentType
from myrm_agent_harness.agent.artifacts.ui_registry import (
    _PENDING_BY_MESSAGE_ID,
    _RUN_MESSAGE_ID_BY_SESSION,
    get_ui_registry,
)
from myrm_agent_harness.agent.meta_tools.interaction.a2ui_spec import (
    A2UI_REFERENCE_FILENAME,
    allowed_component_type_names,
    format_action_reference_error,
    format_adjacency_error,
    format_validation_error,
    get_bundled_reference_content,
    normalize_component_dicts,
    parse_reference_allowed_types,
    seed_reference_to_workspace,
    validate_action_references,
    validate_ui_adjacency,
)
from myrm_agent_harness.agent.meta_tools.interaction.render_ui_tool import render_ui, render_ui_tool


@pytest.fixture(autouse=True)
def _clean_ui_globals(monkeypatch):
    """Prevent cross-test pollution from global UI registry state."""
    _RUN_MESSAGE_ID_BY_SESSION.clear()
    _PENDING_BY_MESSAGE_ID.clear()
    monkeypatch.setattr(_ui_reg_mod, "_CURRENT_RUN_UI_MESSAGE_ID", None)
    from myrm_agent_harness.agent.meta_tools.file_ops.observers.snapshot_observer import (
        _current_message_id as _snapshot_msg_id_var,
    )
    from myrm_agent_harness.agent.middlewares._session_context import _active_message_id_var

    _active_message_id_var.set(None)
    _snapshot_msg_id_var.set(None)
    yield
    _RUN_MESSAGE_ID_BY_SESSION.clear()
    _PENDING_BY_MESSAGE_ID.clear()
    _active_message_id_var.set(None)
    _snapshot_msg_id_var.set(None)


class TestA2uiSpec:
    def test_allowed_types_match_reference_header(self) -> None:
        allowed = set(allowed_component_type_names())
        md_types = set(parse_reference_allowed_types())
        assert md_types == allowed
        assert len(md_types) == len(allowed)

    def test_seed_reference_to_workspace(self, tmp_path: Path) -> None:
        dest = seed_reference_to_workspace(tmp_path)
        assert dest is not None
        assert dest.name == A2UI_REFERENCE_FILENAME
        assert dest.read_text(encoding="utf-8") == get_bundled_reference_content()
        # Idempotent
        assert seed_reference_to_workspace(tmp_path) == dest

    def test_format_validation_error_lists_allowed_types(self) -> None:
        msg = format_validation_error(["bad_type"])
        assert "bad_type" in msg
        assert "text" in msg
        assert ".agent/docs/A2UI_REFERENCE.md" in msg

    def test_format_adjacency_error(self) -> None:
        msg = format_adjacency_error(["root_id not found: missing"])
        assert "invalid UI graph" in msg
        assert "missing" in msg

    def test_normalize_component_dicts_preserves_explicit_type(self) -> None:
        normalized = normalize_component_dicts([{"id": "c", "type": "card", "props": {}}])
        assert normalized[0]["type"] == "card"

    def test_normalize_component_dicts_infers_button_from_events(self) -> None:
        normalized = normalize_component_dicts([{"id": "b", "props": {}, "events": {"onClick": "go"}}])
        assert normalized[0]["type"] == "button"

    def test_normalize_component_dicts_infers_text_field_from_label(self) -> None:
        normalized = normalize_component_dicts([{"id": "n", "props": {"label": "Name"}}])
        assert normalized[0]["type"] == "text_field"

    def test_normalize_component_dicts_infers_text_from_text_prop(self) -> None:
        normalized = normalize_component_dicts([{"id": "t", "props": {"text": "Hi"}}])
        assert normalized[0]["type"] == "text"

    def test_normalize_component_dicts_defaults_unknown_props_to_text(self) -> None:
        normalized = normalize_component_dicts([{"id": "x", "props": {}}])
        assert normalized[0]["type"] == "text"

    def test_normalize_component_dicts_passes_through_non_dict_entries(self) -> None:
        raw: list[dict[str, object]] = [{"id": "a", "type": "text", "props": {"text": "x"}}, "junk"]  # type: ignore[list-item]
        normalized = normalize_component_dicts(raw)
        assert normalized == raw

    def test_validate_ui_adjacency_detects_missing_root(self) -> None:
        errors = validate_ui_adjacency(
            [{"id": "a", "type": "text", "props": {}}],
            ["ghost"],
        )
        assert "root_id not found: ghost" in errors

    def test_validate_ui_adjacency_detects_missing_child(self) -> None:
        errors = validate_ui_adjacency(
            [{"id": "parent", "type": "card", "children": ["missing_child"], "props": {}}],
            ["parent"],
        )
        assert any("child id not found" in err for err in errors)

    def test_validate_ui_adjacency_detects_duplicate_ids(self) -> None:
        errors = validate_ui_adjacency(
            [
                {"id": "dup", "type": "text", "props": {}},
                {"id": "dup", "type": "text", "props": {}},
            ],
            ["dup"],
        )
        assert "duplicate component id: dup" in errors

    def test_validate_action_references_detects_unknown_action(self) -> None:
        errors = validate_action_references(
            [{"id": "btn", "type": "button", "events": {"onClick": "ghost"}}],
            [{"id": "submit", "type": "submit", "label": "Go"}],
        )
        assert len(errors) == 1
        assert "references unknown action id: ghost" in errors[0]

    def test_validate_action_references_detects_empty_action_id(self) -> None:
        errors = validate_action_references(
            [{"id": "btn", "type": "button", "events": {"onClick": ""}}],
            [{"id": "submit", "type": "submit", "label": "Go"}],
        )
        assert len(errors) == 1
        assert "empty action id" in errors[0]

    def test_validate_action_references_detects_missing_actions_list(self) -> None:
        errors = validate_action_references(
            [{"id": "btn", "type": "button", "events": {"onClick": "go"}}],
            None,
        )
        assert len(errors) == 1
        assert "unknown action id: go" in errors[0]

    def test_validate_action_references_passes_valid_bindings(self) -> None:
        errors = validate_action_references(
            [
                {"id": "btn", "type": "button", "events": {"onClick": "go"}},
                {"id": "note", "type": "text", "props": {"text": "x"}},
            ],
            [{"id": "go", "type": "submit", "label": "Go"}],
        )
        assert errors == ()

    def test_validate_action_references_mixed_valid_and_invalid(self) -> None:
        errors = validate_action_references(
            [
                {"id": "ok", "type": "button", "events": {"onClick": "go"}},
                {"id": "bad", "type": "button", "events": {"onClick": "ghost"}},
                {"id": "plain", "type": "text", "props": {"text": "x"}},
            ],
            [{"id": "go", "type": "submit", "label": "Go"}],
        )
        assert len(errors) == 1
        assert "bad" in errors[0]
        assert "ghost" in errors[0]

    def test_validate_action_references_skips_non_dict_events(self) -> None:
        errors = validate_action_references(
            [{"id": "x", "type": "text", "events": None}],
            [{"id": "go", "type": "submit", "label": "Go"}],
        )
        assert errors == ()

    def test_validate_action_references_exact_match_no_whitespace_normalization(self) -> None:
        """Whitespace is not normalized: the client resolves action ids exactly."""
        errors = validate_action_references(
            [{"id": "btn", "type": "button", "events": {"onClick": "go"}}],
            [{"id": "go ", "type": "submit", "label": "Go"}],
        )
        assert len(errors) == 1
        assert "go" in errors[0]

    def test_validate_action_references_detects_duplicate_action_id(self) -> None:
        errors = validate_action_references(
            [{"id": "btn", "type": "button", "events": {"onClick": "confirm"}}],
            [
                {"id": "confirm", "type": "submit", "label": "确认"},
                {"id": "confirm", "type": "cancel", "label": "取消"},
            ],
        )
        assert "duplicate action id: confirm" in errors

    def test_validate_action_references_unique_ids_pass(self) -> None:
        errors = validate_action_references(
            [
                {"id": "ok", "type": "button", "events": {"onClick": "submit"}},
                {"id": "cancel", "type": "button", "events": {"onClick": "cancel"}},
            ],
            [
                {"id": "submit", "type": "submit", "label": "确认"},
                {"id": "cancel", "type": "cancel", "label": "取消"},
            ],
        )
        assert errors == ()

    def test_format_action_reference_error(self) -> None:
        msg = format_action_reference_error(["component btn: event 'onClick' references unknown action id: ghost"])
        assert "invalid action reference(s)" in msg
        assert "ghost" in msg

    def test_seed_returns_none_for_non_directory(self, tmp_path: Path) -> None:
        file_path = tmp_path / "not_a_dir"
        file_path.write_text("x", encoding="utf-8")
        assert seed_reference_to_workspace(file_path) is None

    def test_parse_reference_multiline_blockquote(self) -> None:
        content = "> Allowed types (must match):\n> text, button, card"
        assert parse_reference_allowed_types(content) == ("text", "button", "card")

    def test_parse_reference_empty_when_no_header(self) -> None:
        assert parse_reference_allowed_types("# Title only\n\nBody") == ()

    def test_parse_reference_empty_when_no_colon_types(self) -> None:
        assert parse_reference_allowed_types("> Allowed types without colon list") == ()

    def test_seed_overwrites_when_bundled_content_changes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dest = seed_reference_to_workspace(tmp_path)
        assert dest is not None
        monkeypatch.setattr(
            "myrm_agent_harness.agent.meta_tools.interaction.a2ui_spec.get_bundled_reference_content",
            lambda: "updated bundled content",
        )
        updated = seed_reference_to_workspace(tmp_path)
        assert updated is not None
        assert updated.read_text(encoding="utf-8") == "updated bundled content"


class TestRenderUiSuccessAndEdges:
    def test_render_basic_success_registers_artifact(self) -> None:
        with ArtifactContextManager():
            result = render_ui(
                title="用户信息",
                components=[
                    {
                        "id": "name",
                        "type": "text_field",
                        "props": {"label": "姓名"},
                        "bindings": {"value": "$.form.name"},
                    },
                ],
                root_ids=["name"],
                data={"form": {"name": ""}},
                actions=[{"id": "submit", "type": "submit", "label": "提交"}],
            )
            assert "用户信息" in result
            registry = get_ui_registry()
            assert registry is not None
            events = registry.pop_pending_events()
            assert len(events) == 1
            assert events[0].data == {"form": {"name": ""}}
            assert len(events[0].actions) == 1

    def test_missing_component_type_inferred_from_props(self) -> None:
        inferred = normalize_component_dicts([{"id": "t1", "props": {"text": "hello"}}])
        assert inferred[0]["type"] == "text"

        with ArtifactContextManager():
            result = render_ui(
                title="Inferred",
                components=[{"id": "t1", "props": {"text": "hello"}}],
                root_ids=["t1"],
            )
            assert "Inferred" in result
            registry = get_ui_registry()
            assert registry is not None
            events = registry.pop_pending_events()
            assert len(events) == 1
            assert events[0].components[0].type == UIComponentType.TEXT

    def test_empty_props_without_type_defaults_to_text(self) -> None:
        with ArtifactContextManager():
            result = render_ui(
                title="DefaultText",
                components=[{"id": "x", "props": {}}],
                root_ids=["x"],
            )
            assert "DefaultText" in result
            registry = get_ui_registry()
            assert registry is not None
            assert registry.has_pending_events()

    def test_invalid_action_type_defaults_to_custom(self) -> None:
        with ArtifactContextManager():
            render_ui(
                title="Actions",
                components=[{"id": "btn", "type": "button", "props": {"label": "Go"}}],
                root_ids=["btn"],
                actions=[{"id": "a1", "type": "not_a_real_type", "label": "X"}],
            )
            registry = get_ui_registry()
            assert registry is not None
            events = registry.pop_pending_events()
            assert events[0].actions[0].type == "custom"

    def test_non_dict_action_entry_fail_closed(self) -> None:
        with ArtifactContextManager():
            result = render_ui(
                title="Actions",
                components=[{"id": "btn", "type": "button", "props": {"label": "Go"}}],
                root_ids=["btn"],
                actions=[{"id": "a1", "type": "submit", "label": "OK"}, "skip-me"],  # type: ignore[list-item]
            )
            assert result.startswith("Failed to render UI")
            assert "actions[1]" in result
            registry = get_ui_registry()
            assert registry is not None
            assert not registry.has_pending_events()

    def test_render_ui_fail_closed_on_dangling_action_reference(self) -> None:
        with ArtifactContextManager():
            result = render_ui(
                title="Dangling",
                components=[{"id": "btn", "type": "button", "props": {"label": "Go"}, "events": {"onClick": "ghost"}}],
                root_ids=["btn"],
                actions=[{"id": "real", "type": "submit", "label": "Real"}],
            )
            assert result.startswith("Failed to render UI")
            assert "invalid action reference(s)" in result
            assert "ghost" in result
            registry = get_ui_registry()
            assert registry is not None
            assert not registry.has_pending_events()

    def test_render_ui_passes_when_events_resolve(self) -> None:
        with ArtifactContextManager():
            result = render_ui(
                title="Resolved",
                components=[{"id": "btn", "type": "button", "props": {"label": "Go"}, "events": {"onClick": "go"}}],
                root_ids=["btn"],
                actions=[{"id": "go", "type": "submit", "label": "Go"}],
            )
            assert "Resolved" in result
            registry = get_ui_registry()
            assert registry is not None
            assert registry.has_pending_events()

    def test_render_ui_fail_closed_when_actions_missing_but_events_referenced(self) -> None:
        with ArtifactContextManager():
            result = render_ui(
                title="No actions",
                components=[{"id": "btn", "type": "button", "props": {"label": "Go"}, "events": {"onClick": "go"}}],
                root_ids=["btn"],
            )
            assert result.startswith("Failed to render UI")
            assert "invalid action reference(s)" in result
            registry = get_ui_registry()
            assert registry is not None
            assert not registry.has_pending_events()

    def test_render_ui_fail_closed_on_duplicate_action_id(self) -> None:
        with ArtifactContextManager():
            result = render_ui(
                title="Duplicate action",
                components=[
                    {"id": "btn", "type": "button", "props": {"label": "Go"}, "events": {"onClick": "confirm"}}
                ],
                root_ids=["btn"],
                actions=[
                    {"id": "confirm", "type": "submit", "label": "确认"},
                    {"id": "confirm", "type": "cancel", "label": "取消"},
                ],
            )
            assert result.startswith("Failed to render UI")
            assert "duplicate action id: confirm" in result
            registry = get_ui_registry()
            assert registry is not None
            assert not registry.has_pending_events()

    def test_render_ui_success_returns_surface_id(self) -> None:
        with ArtifactContextManager():
            result = render_ui(
                title="Surface",
                components=[{"id": "t", "type": "text", "props": {"text": "x"}}],
                root_ids=["t"],
            )
            registry = get_ui_registry()
            assert registry is not None
            events = registry.pop_pending_events()
            assert len(events) == 1
            assert f"surface_id={events[0].surface_id}" in result

    def test_render_outside_artifact_context_returns_error(self) -> None:
        from myrm_agent_harness.agent.artifacts.ui_registry import pop_run_message_id

        pop_run_message_id("")
        result = render_ui(
            title="No Context",
            components=[{"id": "t", "type": "text", "props": {"text": "x"}}],
            root_ids=["t"],
        )
        assert result.startswith("Failed to render UI")
        assert "registry is not initialized" in result

    def test_render_ui_returns_error_on_unexpected_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("registry exploded")

        with ArtifactContextManager():
            registry = get_ui_registry()
            assert registry is not None
            monkeypatch.setattr(registry, "add_ui", _boom)
            result = render_ui(
                title="Broken",
                components=[{"id": "t", "type": "text", "props": {"text": "x"}}],
                root_ids=["t"],
            )
            assert result.startswith("Failed to render UI: RuntimeError: registry exploded")

    def test_render_ui_dispatches_realtime_ui_update_custom_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """render_ui must emit LangGraph custom ui_update for stream_dispatcher realtime path."""
        captured: list[tuple[str, object]] = []

        def _capture(name: str, payload: object) -> None:
            captured.append((name, payload))

        monkeypatch.setattr(
            "langchain_core.callbacks.manager.dispatch_custom_event",
            _capture,
        )

        with ArtifactContextManager():
            result = render_ui(
                title="Realtime",
                components=[{"id": "t1", "type": "text", "props": {"text": "live"}}],
                root_ids=["t1"],
            )

        assert "Realtime" in result
        assert len(captured) == 1
        assert captured[0][0] == "ui_update"
        payload = captured[0][1]
        assert isinstance(payload, dict)
        assert payload.get("subtype") == "ui_artifact"
        data = payload.get("data")
        assert isinstance(data, list) and data[0]["title"] == "Realtime"


class TestRenderUiFailClosed:
    def test_unknown_component_type_returns_error(self) -> None:
        with ArtifactContextManager():
            result = render_ui(
                title="Test",
                components=[
                    {"id": "valid", "type": "text", "props": {"text": "hello"}},
                    {"id": "invalid", "type": "nonexistent_type", "props": {}},
                ],
                root_ids=["valid"],
            )
            assert result.startswith("Failed to render UI")
            assert "nonexistent_type" in result
            registry = get_ui_registry()
            assert registry is not None
            assert not registry.has_pending_events()

    def test_empty_components_returns_error(self) -> None:
        with ArtifactContextManager():
            result = render_ui(title="Empty", components=[], root_ids=[])
            assert "components must not be empty" in result

    def test_empty_root_ids_returns_error(self) -> None:
        with ArtifactContextManager():
            result = render_ui(
                title="No roots",
                components=[{"id": "t", "type": "text", "props": {"text": "x"}}],
                root_ids=[],
            )
            assert "invalid UI graph" in result
            assert "root_ids must not be empty" in result

    def test_unknown_root_id_returns_error(self) -> None:
        with ArtifactContextManager():
            result = render_ui(
                title="Bad root",
                components=[{"id": "t", "type": "text", "props": {"text": "x"}}],
                root_ids=["missing"],
            )
            assert "invalid UI graph" in result
            assert "root_id not found: missing" in result

    def test_slim_docstring_under_token_budget(self) -> None:
        doc = render_ui.__doc__ or ""
        assert len(doc) < 3000

    def test_render_ui_tool_description_measured_tokens(self) -> None:
        encoding = tiktoken.get_encoding("cl100k_base")
        description = render_ui_tool.description or ""
        token_count = len(encoding.encode(description))
        assert token_count < 1500
        assert token_count >= 150
