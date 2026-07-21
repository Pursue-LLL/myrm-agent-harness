"""Additional coverage for file_read_handlers and file_read_tool vault-adjacent paths."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers import (
    _dispatch_truncation_event,
    _read_via_service,
    append_media_text_parts,
    build_multimodal_result,
    process_text_paths,
)
from myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool import (
    FileReadInput,
    create_file_read_tool,
)
from myrm_agent_harness.utils.errors import ToolError

_DUMMY_CONFIG = RunnableConfig()


class TestFileReadInputNormalization:
    def test_normalize_json_string_paths(self) -> None:
        model = FileReadInput(paths='["a.txt", "b.txt"]')
        assert model.paths == ["a.txt", "b.txt"]

    def test_normalize_single_string_path(self) -> None:
        model = FileReadInput(paths="solo.txt")
        assert model.paths == ["solo.txt"]

    def test_normalize_list_paths(self) -> None:
        model = FileReadInput(paths=["x.py"])
        assert model.paths == ["x.py"]


@pytest.mark.asyncio
async def test_build_multimodal_vision_and_pdf(tmp_path: Path) -> None:
    img = tmp_path / "pic.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    mock_executor = MagicMock()
    mock_executor.workspace_path = str(tmp_path)

    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers.read_image_as_content_blocks",
        new_callable=AsyncMock,
        return_value=[{"type": "text", "text": "img block"}],
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers.read_pdf_as_content_blocks",
        new_callable=AsyncMock,
        return_value="pdf text",
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers.read_video_as_content_blocks",
        new_callable=AsyncMock,
        return_value="video text",
    ):
        blocks = await build_multimodal_result(
            image_paths=[str(img)],
            pdf_paths=[str(pdf)],
            document_paths=[],
            text_paths=["notes.txt"],
            vault_paths=[],
            executor=mock_executor,
            skills=None,
            reason="test",
            url_errors=[],
            supports_vision=True,
            video_paths=[str(tmp_path / "clip.mp4")],
            config=_DUMMY_CONFIG,
        )

    texts = [b["text"] for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
    assert any("img block" in t for t in texts)
    assert any("pdf text" in t for t in texts)
    assert any("video text" in t for t in texts)


@pytest.mark.asyncio
async def test_append_media_vision_fallback_path() -> None:
    mock_executor = MagicMock()
    parts: list[str] = []
    with patch(
        "myrm_agent_harness.toolkits.llms.vision.fallback_engine.VisionFallbackEngine.describe_local_image",
        new_callable=AsyncMock,
        return_value="described",
    ):
        await append_media_text_parts(
            parts,
            image_paths=["z.png"],
            pdf_paths=[],
            document_paths=[],
            video_paths=[],
            executor=mock_executor,
            supports_vision=False,
            vision_fallback_model_cfg={"model": "gpt-4o-mini", "api_key": "k"},
            excel_mode=None,
        )
    assert "described" in parts[0]


@pytest.mark.asyncio
async def test_build_multimodal_pdf_list_blocks() -> None:
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers.read_pdf_as_content_blocks",
        new_callable=AsyncMock,
        return_value=[{"type": "text", "text": "pdf blocks"}],
    ):
        blocks = await build_multimodal_result(
            image_paths=[],
            pdf_paths=["a.pdf"],
            document_paths=[],
            text_paths=[],
            vault_paths=[],
            executor=MagicMock(),
            skills=None,
            reason=None,
            url_errors=[],
            supports_vision=True,
            config=_DUMMY_CONFIG,
        )
    assert any("pdf blocks" in b.get("text", "") for b in blocks if isinstance(b, dict))

    blocks = await build_multimodal_result(
        image_paths=[],
        pdf_paths=[],
        document_paths=[],
        text_paths=[],
        vault_paths=[],
        executor=MagicMock(),
        skills=None,
        reason=None,
        url_errors=[],
        supports_vision=False,
        config=_DUMMY_CONFIG,
    )
    assert blocks[0]["text"] == "No results."


@pytest.mark.asyncio
async def test_append_media_text_parts_with_executor(tmp_path: Path) -> None:
    mock_executor = MagicMock()
    parts: list[str] = []
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers.read_image_as_content_blocks",
        new_callable=AsyncMock,
        return_value="image text",
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers.read_pdf_as_content_blocks",
        new_callable=AsyncMock,
        return_value="pdf text",
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers.read_document_as_text",
        new_callable=AsyncMock,
        return_value="doc text",
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers.read_video_as_content_blocks",
        new_callable=AsyncMock,
        return_value="video text",
    ):
        await append_media_text_parts(
            parts,
            image_paths=["a.png"],
            pdf_paths=["b.pdf"],
            document_paths=["c.docx"],
            video_paths=["d.mp4"],
            executor=mock_executor,
            supports_vision=True,
            vision_fallback_model_cfg=None,
            excel_mode=None,
        )
    assert parts == ["image text", "pdf text", "doc text", "video text"]


@pytest.mark.asyncio
async def test_read_via_service_dispatches_truncation_event() -> None:
    mock_service = MagicMock()
    mock_service.execute = AsyncMock(return_value="long output")
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers.FileOperationService",
        return_value=mock_service,
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers.truncate_file_output",
        return_value=("short", True, {"tokens": 1}),
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers._dispatch_truncation_event",
        new_callable=AsyncMock,
    ) as mock_dispatch:
        out = await _read_via_service("f.txt", MagicMock(), None, None, config=_DUMMY_CONFIG)
    assert out == "short"
    mock_dispatch.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_truncation_event() -> None:
    with patch(
        "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
        new_callable=AsyncMock,
    ) as mock_event:
        await _dispatch_truncation_event({"k": "v"}, tool="file_read", config=_DUMMY_CONFIG)
    mock_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_text_paths_preview_mode(tmp_path: Path) -> None:
    big = tmp_path / "big.txt"
    big.write_text("line\n" * 50, encoding="utf-8")
    mock_executor = MagicMock()
    mock_executor.workspace_path = str(tmp_path)

    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers.read_file_preview",
        new_callable=AsyncMock,
        return_value="preview chunk",
    ):
        parts = await process_text_paths(
            [str(big)],
            mock_executor,
            None,
            None,
            "preview",
            10,
            config=_DUMMY_CONFIG,
        )
    assert "preview mode" in parts[0]
    assert "preview chunk" in parts[0]


@pytest.mark.asyncio
async def test_process_text_paths_stream_mode(tmp_path: Path) -> None:
    f = tmp_path / "stream.txt"
    f.write_text("stream data\n", encoding="utf-8")
    mock_executor = MagicMock()
    mock_executor.workspace_path = str(tmp_path)

    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers.read_file_chunked",
        new_callable=AsyncMock,
        return_value="chunked",
    ):
        parts = await process_text_paths(
            [str(f)],
            mock_executor,
            None,
            None,
            "stream",
            5,
            config=_DUMMY_CONFIG,
        )
    assert "chunked" in parts[0]


@pytest.mark.asyncio
async def test_file_read_tool_multimodal_with_preserve_context(tmp_path: Path) -> None:
    img = tmp_path / "chart.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    mock_executor = MagicMock()
    mock_executor.workspace_path = str(tmp_path)

    tool = create_file_read_tool()
    ctx = {"supports_vision": True}
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_executor",
        return_value=mock_executor,
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.extract_context_from_runnable_config",
        return_value=ctx,
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers.read_image_as_content_blocks",
        new_callable=AsyncMock,
        return_value=[{"type": "text", "text": "vision ok"}],
    ):
        result = await tool.ainvoke(
            {"paths": [str(img)], "preserve_in_context": True},
            config=_DUMMY_CONFIG,
        )

    assert isinstance(result, list)
    texts = [b["text"] for b in result if isinstance(b, dict)]
    assert any("<preserve_context>" in t for t in texts)


@pytest.mark.asyncio
async def test_file_read_tool_raises_tool_error_on_missing_file() -> None:
    tool = create_file_read_tool()
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_executor",
        return_value=MagicMock(workspace_path="/tmp"),
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.process_text_paths",
        new_callable=AsyncMock,
        side_effect=FileNotFoundError("missing"),
    ):
        with pytest.raises(ToolError, match="missing"):
            await tool.ainvoke({"paths": ["missing.txt"]}, config=_DUMMY_CONFIG)


@pytest.mark.asyncio
async def test_file_read_tool_raises_tool_error_on_permission_error() -> None:
    tool = create_file_read_tool()
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_executor",
        return_value=MagicMock(workspace_path="/tmp"),
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.process_text_paths",
        new_callable=AsyncMock,
        side_effect=PermissionError("denied"),
    ):
        with pytest.raises(ToolError, match="denied"):
            await tool.ainvoke({"paths": ["secret.txt"]}, config=_DUMMY_CONFIG)


@pytest.mark.asyncio
async def test_file_read_tool_raises_tool_error_on_unexpected() -> None:
    tool = create_file_read_tool()
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_executor",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(ToolError, match="Unexpected error"):
            await tool.ainvoke({"paths": ["x.txt"]}, config=_DUMMY_CONFIG)


@pytest.mark.asyncio
async def test_file_read_tool_text_preserve_in_context(tmp_path: Path) -> None:
    f = tmp_path / "note.txt"
    f.write_text("note", encoding="utf-8")
    mock_executor = MagicMock()
    mock_executor.workspace_path = str(tmp_path)
    tool = create_file_read_tool()
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_executor",
        return_value=mock_executor,
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers.process_text_paths",
        new_callable=AsyncMock,
        return_value=["note body"],
    ):
        result = await tool.ainvoke(
            {"paths": [str(f)], "preserve_in_context": True},
            config=_DUMMY_CONFIG,
        )
    assert isinstance(result, str)
    assert "<preserve_context>" in result


@pytest.mark.asyncio
async def test_build_multimodal_image_list_blocks() -> None:
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers.read_image_as_content_blocks",
        new_callable=AsyncMock,
        return_value=[{"type": "text", "text": "img-list"}],
    ):
        blocks = await build_multimodal_result(
            image_paths=["a.png"],
            pdf_paths=[],
            document_paths=[],
            text_paths=[],
            vault_paths=[],
            executor=MagicMock(),
            skills=None,
            reason=None,
            url_errors=[],
            supports_vision=True,
            config=_DUMMY_CONFIG,
        )
    assert any("img-list" in b.get("text", "") for b in blocks if isinstance(b, dict))


@pytest.mark.asyncio
async def test_build_multimodal_image_no_vision_string_result() -> None:
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers.read_image_as_content_blocks",
        new_callable=AsyncMock,
        return_value="plain image text",
    ):
        blocks = await build_multimodal_result(
            image_paths=["a.png"],
            pdf_paths=[],
            document_paths=[],
            text_paths=[],
            vault_paths=[],
            executor=MagicMock(),
            skills=None,
            reason=None,
            url_errors=[],
            supports_vision=False,
            config=_DUMMY_CONFIG,
        )
    assert blocks[0]["text"] == "plain image text"


@pytest.mark.asyncio
async def test_build_multimodal_video_list_blocks() -> None:
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers.read_video_as_content_blocks",
        new_callable=AsyncMock,
        return_value=[{"type": "text", "text": "vid-list"}],
    ):
        blocks = await build_multimodal_result(
            image_paths=[],
            pdf_paths=[],
            document_paths=[],
            text_paths=[],
            vault_paths=[],
            executor=MagicMock(),
            skills=None,
            reason=None,
            url_errors=[],
            supports_vision=True,
            video_paths=["clip.mp4"],
            config=_DUMMY_CONFIG,
        )
    assert any("vid-list" in b.get("text", "") for b in blocks if isinstance(b, dict))


@pytest.mark.asyncio
async def test_append_media_vision_fallback_failure() -> None:
    mock_executor = MagicMock()
    parts: list[str] = []
    with patch(
        "myrm_agent_harness.toolkits.llms.vision.fallback_engine.VisionFallbackEngine.describe_local_image",
        new_callable=AsyncMock,
        side_effect=RuntimeError("api down"),
    ):
        await append_media_text_parts(
            parts,
            image_paths=["z.png"],
            pdf_paths=[],
            document_paths=[],
            video_paths=[],
            executor=mock_executor,
            supports_vision=False,
            vision_fallback_model_cfg={"model": "gpt-4o-mini", "api_key": "k"},
            excel_mode=None,
        )
    assert "Vision fallback failed" in parts[0]


@pytest.mark.asyncio
async def test_process_text_paths_mcp_and_directory(tmp_path: Path) -> None:
    mock_executor = MagicMock()
    mock_executor.workspace_path = str(tmp_path)
    d = tmp_path / "folder"
    d.mkdir()

    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers._read_via_service",
        new_callable=AsyncMock,
        side_effect=["mcp content", "dir listing"],
    ) as mock_read:
        parts = await process_text_paths(
            ["/mcp/skill/doc.md", str(d)],
            mock_executor,
            None,
            None,
            "all",
            10,
            config=_DUMMY_CONFIG,
        )
    assert parts == ["mcp content", "dir listing"]
    assert mock_read.await_count == 2


@pytest.mark.asyncio
async def test_process_text_paths_exception_fallback(tmp_path: Path) -> None:
    f = tmp_path / "broken.txt"
    f.write_text("ok", encoding="utf-8")
    mock_executor = MagicMock()
    mock_executor.workspace_path = str(tmp_path)

    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers.read_file_preview",
        new_callable=AsyncMock,
        side_effect=OSError("read fail"),
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_handlers._read_via_service",
        new_callable=AsyncMock,
        return_value="fallback content",
    ) as mock_service:
        parts = await process_text_paths(
            [str(f)],
            mock_executor,
            None,
            None,
            "preview",
            10,
            config=_DUMMY_CONFIG,
        )
    mock_service.assert_awaited()
    assert parts[-1] == "fallback content"


@pytest.mark.asyncio
async def test_file_read_blocks_disabled_skill_path() -> None:
    tool = create_file_read_tool()
    mock_executor = MagicMock()
    mock_executor.resolve_path = AsyncMock(return_value="/workspace/skills/off/secret.md")
    config = RunnableConfig(
        configurable={"context": {"disabled_skill_roots": ["/workspace/skills/off"]}},
    )

    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_executor",
        return_value=mock_executor,
    ):
        with pytest.raises(ToolError, match="blocked"):
            await tool.ainvoke({"paths": ["skills/off/secret.md"]}, config=config)


@pytest.mark.asyncio
async def test_file_read_file_not_found_includes_similar_path_hint(tmp_path: Path) -> None:
    tool = create_file_read_tool()
    (tmp_path / "readme.md").write_text("hello", encoding="utf-8")
    target = str(tmp_path / "redme.md")
    mock_executor = MagicMock()
    mock_executor.resolve_path = AsyncMock(return_value=target)

    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_executor",
        return_value=mock_executor,
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.process_text_paths",
        new_callable=AsyncMock,
        side_effect=FileNotFoundError(f"not found: {target}"),
    ):
        with pytest.raises(ToolError) as exc_info:
            await tool.ainvoke({"paths": [target]}, config=_DUMMY_CONFIG)

    assert exc_info.value.user_hint is not None
    assert "Did you mean" in exc_info.value.user_hint


@pytest.mark.asyncio
async def test_file_read_rejects_url_paths_only() -> None:
    tool = create_file_read_tool()
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_executor",
        return_value=MagicMock(),
    ):
        result = await tool.ainvoke({"paths": ["https://example.com/doc"]}, config=_DUMMY_CONFIG)
    assert isinstance(result, str)
    assert "cannot read URLs" in result


@pytest.mark.asyncio
async def test_file_read_raises_value_error_when_no_valid_paths() -> None:
    tool = create_file_read_tool()
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_executor",
        return_value=MagicMock(),
    ):
        with pytest.raises(ToolError) as exc_info:
            await tool.ainvoke({"paths": []}, config=_DUMMY_CONFIG)
    assert exc_info.value.user_hint is not None
    assert "Invalid parameter" in exc_info.value.user_hint


@pytest.mark.asyncio
async def test_file_read_permission_error_wrapped() -> None:
    tool = create_file_read_tool()
    mock_executor = MagicMock()
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_executor",
        return_value=mock_executor,
    ), patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.process_text_paths",
        new_callable=AsyncMock,
        side_effect=PermissionError("denied"),
    ):
        with pytest.raises(ToolError) as exc_info:
            await tool.ainvoke({"paths": ["secret.txt"]}, config=_DUMMY_CONFIG)
    assert exc_info.value.user_hint is not None
    assert "Permission denied" in exc_info.value.user_hint


@pytest.mark.asyncio
async def test_file_read_disabled_path_when_resolve_raises_value_error() -> None:
    tool = create_file_read_tool()
    mock_executor = MagicMock()
    mock_executor.resolve_path = AsyncMock(side_effect=ValueError("bad path"))
    config = RunnableConfig(
        configurable={"context": {"disabled_skill_roots": ["/workspace/skills/off"]}},
    )
    with patch(
        "myrm_agent_harness.agent.meta_tools.file_ops.file_read_tool.get_executor",
        return_value=mock_executor,
    ):
        with pytest.raises(ToolError, match="blocked"):
            await tool.ainvoke(
                {"paths": ["/workspace/skills/off/secret.md"]},
                config=config,
            )

