"""Tests for vault-related paths in file_read_handlers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.artifacts.vault import ArtifactVault
from myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers import (
    append_media_text_parts,
    build_multimodal_result,
    process_text_paths,
)
from myrm_agent_harness.agent.meta_tools.file_ops.utils.vault_read import (
    path_base,
    read_vault_paths_to_parts,
    resolve_workspace_root,
)

_DUMMY_CONFIG = RunnableConfig()


class TestVaultReadUtilities:
    def test_path_base_non_vault_with_colon(self) -> None:
        assert path_base("/tmp/file.py:1-10") == "/tmp/file.py"

    def test_path_base_vault_uri(self, tmp_path: Path) -> None:
        ws = str(tmp_path)
        vault = ArtifactVault(ws)
        pointer = vault.put("x", "a.txt")
        assert path_base(f"{pointer}:2-4") == pointer

    def test_resolve_workspace_root_from_executor(self) -> None:
        executor = MagicMock()
        executor._current_workspace = "/ws/a"
        with patch(
            "myrm_agent_harness.toolkits.code_execution.utils.workspace_path.WorkspacePathResolver.resolve_workspace_root",
            side_effect=RuntimeError("no resolver"),
        ):
            assert resolve_workspace_root(executor) == "/ws/a"

    def test_resolve_workspace_root_unavailable(self) -> None:
        with patch(
            "myrm_agent_harness.toolkits.code_execution.utils.workspace_path.WorkspacePathResolver.resolve_workspace_root",
            side_effect=RuntimeError("no resolver"),
        ):
            assert resolve_workspace_root(None) is None


@pytest.mark.asyncio
async def test_read_vault_paths_to_parts_success(tmp_path: Path) -> None:
    ws = str(tmp_path)
    vault = ArtifactVault(ws)
    pointer = vault.put("vault body\n", "r.md")
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.utils.vault_read.resolve_workspace_root",
        return_value=ws,
    ):
        parts = await read_vault_paths_to_parts([pointer], MagicMock(), "all", config=_DUMMY_CONFIG)
    assert len(parts) == 1
    assert "vault body" in parts[0]


@pytest.mark.asyncio
async def test_read_vault_paths_to_parts_no_workspace() -> None:
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.utils.vault_read.resolve_workspace_root",
        return_value=None,
    ):
        parts = await read_vault_paths_to_parts(["vault://x"], None, "all", config=_DUMMY_CONFIG)
    assert "workspace unavailable" in parts[0]


@pytest.mark.asyncio
async def test_read_vault_paths_to_parts_truncation_event(tmp_path: Path) -> None:
    ws = str(tmp_path)
    vault = ArtifactVault(ws)
    huge = "x\n" * 50000
    pointer = vault.put(huge, "huge.md")
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.utils.vault_read.resolve_workspace_root",
        return_value=ws,
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.utils.vault_read.truncate_file_output",
        return_value=("short preview", True, {"truncated": True}),
    ), patch(
        "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
        new_callable=AsyncMock,
    ) as mock_event:
        parts = await read_vault_paths_to_parts([pointer], MagicMock(), "all", config=_DUMMY_CONFIG)
    assert "short preview" in parts[0]
    mock_event.assert_awaited_once()

    ws = str(tmp_path)
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.utils.vault_read.resolve_workspace_root",
        return_value=ws,
    ):
        parts = await read_vault_paths_to_parts(
            ["vault://00000000-0000-0000-0000-000000000000"],
            MagicMock(),
            "all",
            config=_DUMMY_CONFIG,
        )
    assert "not found" in parts[0].lower()


@pytest.mark.asyncio
async def test_build_multimodal_includes_vault_paths(tmp_path: Path) -> None:
    ws = str(tmp_path)
    vault = ArtifactVault(ws)
    pointer = vault.put("multi vault\n", "m.md")
    mock_executor = MagicMock()
    mock_executor.workspace_path = ws

    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.utils.vault_read.resolve_workspace_root",
        return_value=ws,
    ):
        blocks = await build_multimodal_result(
            image_paths=[],
            pdf_paths=[],
            document_paths=["doc.txt"],
            text_paths=[],
            vault_paths=[pointer],
            executor=mock_executor,
            skills=None,
            reason=None,
            url_errors=["url rejected"],
            supports_vision=False,
            config=_DUMMY_CONFIG,
        )

    texts = [b["text"] for b in blocks if b.get("type") == "text"]
    joined = "\n".join(texts)
    assert "url rejected" in joined
    assert "multi vault" in joined


@pytest.mark.asyncio
async def test_append_media_text_parts_no_executor() -> None:
    parts: list[str] = []
    await append_media_text_parts(
        parts,
        image_paths=["img.png"],
        pdf_paths=["doc.pdf"],
        document_paths=["file.docx"],
        video_paths=["vid.mp4"],
        executor=None,
        supports_vision=False,
        vision_fallback_model_cfg=None,
        excel_mode=None,
    )
    assert len(parts) == 4
    assert all("No workspace filesystem available" in p for p in parts)


@pytest.mark.asyncio
async def test_process_text_paths_via_service(tmp_path: Path) -> None:
    f = tmp_path / "hello.txt"
    f.write_text("hello\n", encoding="utf-8")
    mock_executor = MagicMock()
    mock_executor.workspace_path = str(tmp_path)

    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers._read_via_service",
        new_callable=AsyncMock,
        return_value="=== hello.txt ===\nhello\n",
    ) as mock_read:
        parts = await process_text_paths(
            [f"hello.txt:1-1"],
            mock_executor,
            None,
            None,
            "all",
            10,
            config=_DUMMY_CONFIG,
        )
    assert parts == ["=== hello.txt ===\nhello\n"]
    mock_read.assert_awaited()
