"""Tests for A2UI spec helpers and render_ui fail-closed validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import tiktoken

from myrm_agent_harness.agent.artifacts.context import ArtifactContextManager
from myrm_agent_harness.agent.artifacts.ui_registry import get_ui_registry
from myrm_agent_harness.agent.meta_tools.interaction.a2ui_spec import (
    A2UI_REFERENCE_FILENAME,
    allowed_component_type_names,
    format_allowed_types_line,
    format_validation_error,
    get_bundled_reference_content,
    parse_reference_allowed_types,
    seed_reference_to_workspace,
)
from myrm_agent_harness.agent.meta_tools.interaction.render_ui_tool import render_ui, render_ui_tool


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

    def test_seed_overwrites_when_bundled_content_changes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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

    def test_missing_component_type_fail_closed(self) -> None:
        with ArtifactContextManager():
            result = render_ui(
                title="Bad",
                components=[{"id": "x", "props": {}}],
                root_ids=["x"],
            )
            assert result.startswith("Failed to render UI")
            assert "<missing>" in result
            registry = get_ui_registry()
            assert registry is not None
            assert not registry.has_pending_events()

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

    def test_non_dict_action_entry_is_skipped(self) -> None:
        with ArtifactContextManager():
            render_ui(
                title="Actions",
                components=[{"id": "btn", "type": "button", "props": {"label": "Go"}}],
                root_ids=["btn"],
                actions=[{"id": "a1", "type": "submit", "label": "OK"}, "skip-me"],  # type: ignore[list-item]
            )
            registry = get_ui_registry()
            assert registry is not None
            events = registry.pop_pending_events()
            assert len(events[0].actions) == 1

    def test_render_outside_artifact_context_still_returns_message(self) -> None:
        result = render_ui(
            title="No Context",
            components=[{"id": "t", "type": "text", "props": {"text": "x"}}],
            root_ids=["t"],
        )
        assert "No Context" in result

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

    def test_slim_docstring_under_token_budget(self) -> None:
        doc = render_ui.__doc__ or ""
        assert len(doc) < 2200

    def test_render_ui_tool_description_measured_tokens(self) -> None:
        encoding = tiktoken.get_encoding("cl100k_base")
        description = render_ui_tool.description or ""
        token_count = len(encoding.encode(description))
        assert token_count < 300
        assert token_count >= 150
