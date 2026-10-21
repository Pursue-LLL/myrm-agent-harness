"""Tests for short_file_id propagation in artifacts_ready events."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.agent.artifacts.context import ArtifactContextManager
from myrm_agent_harness.agent.artifacts.file_id_registry import register_file
from myrm_agent_harness.agent.artifacts.registry import GeneratedFile, register_generated_files
from myrm_agent_harness.agent.streaming.artifact_events import emit_artifacts_ready_event
from myrm_agent_harness.agent.streaming.types import AgentEventType


async def _collect_emit(message_id: str, context: dict[str, object]) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    async for event in emit_artifacts_ready_event(message_id, context):
        events.append(event)
    return events


@pytest.mark.asyncio
async def test_emit_artifacts_ready_includes_short_file_id(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    report = workspace / "report.md"
    report.write_text("# Hello", encoding="utf-8")

    mock_executor = MagicMock()
    mock_executor.workspace_path = str(workspace)
    mock_executor.read_file_bytes = AsyncMock(return_value=b"# Hello")

    mock_registry = MagicMock()
    mock_registry.__len__ = MagicMock(return_value=1)
    mock_registry.get_all_files.return_value = [
        GeneratedFile(path=str(report.resolve())),
    ]

    with (
        patch(
            "myrm_agent_harness.agent.streaming.artifact_events.get_executor",
            return_value=mock_executor,
        ),
        patch(
            "myrm_agent_harness.agent.streaming.artifact_events.get_artifact_registry",
            return_value=mock_registry,
        ),
        ArtifactContextManager(message_id="msg_short_file"),
    ):
        register_generated_files([str(report.resolve())])
        register_file(str(report.resolve()))

        events = await _collect_emit("msg_short_file", {})

    assert len(events) == 1
    event = events[0]
    assert event["type"] == AgentEventType.ARTIFACTS_READY.value
    data = event["data"]
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]["filename"] == "report.md"
    assert data[0]["short_file_id"] == "@file_001"


@pytest.mark.asyncio
async def test_lookup_short_file_id_resolves_relative_and_absolute(tmp_path: Path) -> None:
    from myrm_agent_harness.agent.artifacts.file_id_registry import (
        lookup_short_file_id,
        register_file,
    )

    report = tmp_path / "notes" / "brief.md"
    report.parent.mkdir(parents=True)
    report.write_text("x", encoding="utf-8")

    with ArtifactContextManager(message_id="msg_path_norm"):
        register_file(str(report))
        assert lookup_short_file_id(str(report)) == "@file_001"
        assert lookup_short_file_id(str(report.parent / "brief.md")) == "@file_001"


@pytest.mark.asyncio
async def test_lookup_short_file_id_returns_none_without_context() -> None:
    from myrm_agent_harness.agent.artifacts.file_id_registry import lookup_short_file_id

    assert lookup_short_file_id("/workspace/a.md") is None
