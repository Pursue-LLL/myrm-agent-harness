"""Tests for A2UI spec helpers and render_ui fail-closed validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from myrm_agent_harness.agent.artifacts.context import ArtifactContextManager
from myrm_agent_harness.agent.artifacts.ui_registry import get_ui_registry
from myrm_agent_harness.agent.meta_tools.interaction.a2ui_spec import (
    A2UI_REFERENCE_FILENAME,
    allowed_component_type_names,
    format_validation_error,
    get_bundled_reference_content,
    seed_reference_to_workspace,
)
from myrm_agent_harness.agent.meta_tools.interaction.render_ui_tool import render_ui


class TestA2uiSpec:
    def test_allowed_types_match_reference_header(self) -> None:
        allowed = set(allowed_component_type_names())
        content = get_bundled_reference_content()
        header = next(line for line in content.splitlines() if line.startswith("> Allowed types"))
        for token in header.split(":", 1)[1].split(","):
            name = token.strip()
            if name:
                assert name in allowed

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
        # ~400 tok budget: 4 chars/token heuristic
        assert len(doc) < 2200
