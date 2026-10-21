"""Unit tests for ArtifactObserver registration and realtime content push."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from myrm_agent_harness.agent.meta_tools.file_ops.observers.artifact_observer import (
    ArtifactObserver,
)


@pytest.fixture
def observer() -> ArtifactObserver:
    return ArtifactObserver()


@pytest.mark.asyncio
async def test_on_file_created_registers_without_executor(
    observer: ArtifactObserver,
) -> None:
    with (
        patch(
            "myrm_agent_harness.agent.artifacts.registry.register_generated_files",
        ) as mock_register,
        patch(
            "myrm_agent_harness.agent.artifacts.file_id_registry.register_file",
        ) as mock_file_id,
        patch.object(observer, "_push_realtime_content") as mock_push,
    ):
        await observer.on_file_created("notes/meeting.md", "# Meeting\n")

    mock_register.assert_called_once_with(["notes/meeting.md"])
    mock_file_id.assert_called_once_with("notes/meeting.md")
    mock_push.assert_called_once_with("notes/meeting.md", "# Meeting\n")


@pytest.mark.asyncio
async def test_on_file_created_resolves_workspace_relative_path(
    observer: ArtifactObserver,
    tmp_path: Path,
) -> None:
    mock_executor = MagicMock()
    mock_executor.workspace_path = str(tmp_path)

    with (
        patch(
            "myrm_agent_harness.toolkits.code_execution.executors.base.get_executor",
            return_value=mock_executor,
        ),
        patch(
            "myrm_agent_harness.agent.artifacts.registry.register_generated_files",
        ) as mock_register,
        patch.object(observer, "_push_realtime_content"),
    ):
        await observer.on_file_created("reports/week.md", "content")

    expected = str((tmp_path / "reports/week.md").resolve())
    mock_register.assert_called_once_with([expected])


@pytest.mark.asyncio
async def test_on_file_created_strips_workspace_prefix(
    observer: ArtifactObserver,
    tmp_path: Path,
) -> None:
    mock_executor = MagicMock()
    mock_executor.workspace_path = str(tmp_path)

    with (
        patch(
            "myrm_agent_harness.toolkits.code_execution.executors.base.get_executor",
            return_value=mock_executor,
        ),
        patch(
            "myrm_agent_harness.agent.artifacts.registry.register_generated_files",
        ) as mock_register,
        patch.object(observer, "_push_realtime_content"),
    ):
        await observer.on_file_created("/workspace/reports/week.md", "content")

    expected = str((tmp_path / "reports/week.md").resolve())
    mock_register.assert_called_once_with([expected])


@pytest.mark.asyncio
async def test_on_file_created_swallows_registration_errors(
    observer: ArtifactObserver,
) -> None:
    with (
        patch(
            "myrm_agent_harness.agent.artifacts.registry.register_generated_files",
            side_effect=RuntimeError("registry unavailable"),
        ),
        patch.object(observer, "_push_realtime_content"),
    ):
        await observer.on_file_created("a.md", "x")


@pytest.mark.asyncio
async def test_on_file_modified_registers_artifact(observer: ArtifactObserver) -> None:
    with (
        patch(
            "myrm_agent_harness.agent.artifacts.registry.register_generated_files",
        ) as mock_register,
        patch(
            "myrm_agent_harness.agent.artifacts.file_id_registry.register_file",
        ) as mock_file_id,
    ):
        await observer.on_file_modified("a.md", "old", "new")

    mock_register.assert_called_once_with(["a.md"])
    mock_file_id.assert_called_once_with("a.md")


@pytest.mark.asyncio
async def test_on_file_modified_resolves_path_with_executor(
    observer: ArtifactObserver,
    tmp_path: Path,
) -> None:
    mock_executor = MagicMock()
    mock_executor.workspace_path = str(tmp_path)

    with (
        patch(
            "myrm_agent_harness.toolkits.code_execution.executors.base.get_executor",
            return_value=mock_executor,
        ),
        patch(
            "myrm_agent_harness.agent.artifacts.registry.register_generated_files",
        ) as mock_register,
    ):
        await observer.on_file_modified("draft.md", "old", "new")

    expected = str((tmp_path / "draft.md").resolve())
    mock_register.assert_called_once_with([expected])


@pytest.mark.asyncio
async def test_on_file_modified_swallows_registration_errors(
    observer: ArtifactObserver,
) -> None:
    with patch(
        "myrm_agent_harness.agent.artifacts.registry.register_generated_files",
        side_effect=RuntimeError("registry unavailable"),
    ):
        await observer.on_file_modified("a.md", "old", "new")


@pytest.mark.asyncio
async def test_on_file_modified_strips_workspace_prefix(
    observer: ArtifactObserver,
    tmp_path: Path,
) -> None:
    mock_executor = MagicMock()
    mock_executor.workspace_path = str(tmp_path)

    with (
        patch(
            "myrm_agent_harness.toolkits.code_execution.executors.base.get_executor",
            return_value=mock_executor,
        ),
        patch(
            "myrm_agent_harness.agent.artifacts.registry.register_generated_files",
        ) as mock_register,
    ):
        await observer.on_file_modified("/workspace/draft.md", "old", "new")

    expected = str((tmp_path / "draft.md").resolve())
    mock_register.assert_called_once_with([expected])


@pytest.mark.asyncio
async def test_on_file_viewed_is_noop(observer: ArtifactObserver) -> None:
    await observer.on_file_viewed("a.md")


def test_push_realtime_content_success(observer: ArtifactObserver) -> None:
    with patch(
        "myrm_agent_harness.agent.artifacts.registry.push_realtime_content",
    ) as mock_push:
        observer._push_realtime_content("dir/report.md", "# title")

    mock_push.assert_called_once()
    kwargs = mock_push.call_args.kwargs
    assert kwargs["filename"] == "report.md"
    assert kwargs["content"] == "# title"
    assert kwargs["is_complete"] is True


def test_push_realtime_content_swallows_errors(observer: ArtifactObserver) -> None:
    with patch(
        "myrm_agent_harness.agent.artifacts.registry.push_realtime_content",
        side_effect=RuntimeError("push failed"),
    ):
        observer._push_realtime_content("a.py", "print(1)")
