"""Execution handlers for file_read_tool (multimodal, text paths, media fallbacks).

[INPUT]
- core::FileOperationService, OperationContext, OperationType (POS: 文件操作服务)
- streaming::read_file_chunked, read_file_preview (POS: large-file streaming reader)
- utils.*_reader (POS: image/pdf/video/document readers)
- utils.vault_read::read_vault_paths_to_parts (POS: vault URI batch reader)
- file_read_truncation::truncate_file_output (POS: output truncation)
- agent.security.redact::redact_sensitive_text (POS: tool output redaction)
- backends.skills.types::SkillMetadata (POS: MCP skill metadata)

[OUTPUT]
- build_multimodal_result: multimodal content blocks for vision/document paths
- append_media_text_parts: text-mode fallbacks for image/pdf/document/video
- process_text_paths: streaming/preview/all text path reads

[POS]
Heavy read logic extracted from file_read_tool to keep the tool factory under 500 lines.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.messages.content import ContentBlock, create_text_block
from langchain_core.runnables import RunnableConfig

from myrm_agent_harness.agent.security.redact import redact_sensitive_text

from .core import FileOperationService, OperationContext, OperationType
from .file_read_truncation import truncate_file_output
from .streaming import read_file_chunked, read_file_preview
from .utils.document_reader import read_document_as_text
from .utils.image_reader import read_image_as_content_blocks
from .utils.pdf_reader import read_pdf_as_content_blocks
from .utils.vault_read import path_base, read_vault_paths_to_parts
from .utils.video_reader import read_video_as_content_blocks

if TYPE_CHECKING:
    from myrm_agent_harness.backends.skills.types import SkillMetadata
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

logger = logging.getLogger(__name__)


async def build_multimodal_result(
    image_paths: list[str],
    pdf_paths: list[str],
    document_paths: list[str],
    text_paths: list[str],
    vault_paths: list[str],
    executor: CodeExecutor,
    skills: list[SkillMetadata] | None,
    reason: str | None,
    url_errors: list[str],
    supports_vision: bool,
    vision_fallback_model_cfg: object | None = None,
    video_paths: list[str] | None = None,
    excel_mode: str | None = None,
    mode: str = "all",
    *,
    config: RunnableConfig,
) -> list[ContentBlock]:
    """Build multimodal result: images/PDFs as content blocks, documents/text as text blocks."""
    blocks: list[ContentBlock] = []

    if url_errors:
        blocks.append(create_text_block("\n".join(url_errors)))

    for img_path in image_paths:
        if supports_vision:
            result = await read_image_as_content_blocks(img_path, executor, supports_vision=True)
            if isinstance(result, list):
                blocks.extend(result)
            else:
                blocks.append(create_text_block(result))
        elif vision_fallback_model_cfg:
            from myrm_agent_harness.agent.config.llm import LLMConfig
            from myrm_agent_harness.toolkits.llms.vision.fallback_engine import VisionFallbackEngine

            try:
                fallback_config = LLMConfig.model_validate(vision_fallback_model_cfg, from_attributes=True)
                fallback_text = await VisionFallbackEngine(fallback_config).describe_local_image(img_path, executor)
                blocks.append(create_text_block(f"[Image Analysis for {img_path}]:\n{fallback_text}"))
            except Exception as e:
                logger.warning("Vision fallback failed for %s: %s", img_path, e)
                blocks.append(create_text_block(f"[Image file: {img_path}] (Vision fallback failed: {e})"))
        else:
            result = await read_image_as_content_blocks(img_path, executor, supports_vision=False)
            if isinstance(result, list):
                blocks.extend(result)
            else:
                blocks.append(create_text_block(result))

    for pdf_path in pdf_paths:
        result = await read_pdf_as_content_blocks(pdf_path, executor, supports_vision=supports_vision)
        if isinstance(result, list):
            blocks.extend(result)
        else:
            blocks.append(create_text_block(result))

    for doc_path in document_paths:
        result = await read_document_as_text(doc_path, executor, excel_mode=excel_mode)
        blocks.append(create_text_block(result))

    for vid_path in video_paths or []:
        result = await read_video_as_content_blocks(
            vid_path,
            executor,
            supports_vision=supports_vision,
            supports_video=False,
            vision_fallback_model_cfg=vision_fallback_model_cfg,
        )
        if isinstance(result, list):
            blocks.extend(result)
        else:
            blocks.append(create_text_block(result))

    if vault_paths:
        vault_parts = await read_vault_paths_to_parts(vault_paths, executor, mode, config=config)
        if vault_parts:
            blocks.append(create_text_block(redact_sensitive_text("\n\n".join(vault_parts))))

    if text_paths:
        op_context = OperationContext(
            operation=OperationType.VIEW,
            executor=executor,
            skills=skills or [],
            paths=text_paths,
            reason=reason,
        )
        service = FileOperationService(op_context)
        text_result = await service.execute()
        if text_result:
            blocks.append(create_text_block(redact_sensitive_text(text_result)))

    return blocks if blocks else [create_text_block("No results.")]


async def append_media_text_parts(
    text_parts: list[str],
    *,
    image_paths: list[str],
    pdf_paths: list[str],
    document_paths: list[str],
    video_paths: list[str],
    executor: CodeExecutor | None,
    supports_vision: bool,
    vision_fallback_model_cfg: object | None,
    excel_mode: str | None,
) -> None:
    """Append text-mode results for media paths when multimodal is unavailable."""
    for img_path in image_paths:
        if executor is not None:
            if supports_vision:
                img_result = await read_image_as_content_blocks(img_path, executor, supports_vision=True)
                if isinstance(img_result, str):
                    text_parts.append(img_result)
            elif vision_fallback_model_cfg:
                from myrm_agent_harness.agent.config.llm import LLMConfig
                from myrm_agent_harness.toolkits.llms.vision.fallback_engine import VisionFallbackEngine

                try:
                    fallback_config = LLMConfig.model_validate(vision_fallback_model_cfg, from_attributes=True)
                    fallback_text = await VisionFallbackEngine(fallback_config).describe_local_image(
                        img_path, executor
                    )
                    text_parts.append(f"[Image Analysis for {img_path}]:\n{fallback_text}")
                except Exception as e:
                    logger.warning("Vision fallback failed for %s: %s", img_path, e)
                    text_parts.append(f"[Image file: {img_path}] (Vision fallback failed: {e})")
            else:
                img_result = await read_image_as_content_blocks(img_path, executor, supports_vision=False)
                if isinstance(img_result, str):
                    text_parts.append(img_result)
        else:
            text_parts.append(f"[Image file: {img_path}] (No workspace filesystem available)")

    for pdf_path in pdf_paths:
        if executor is not None:
            pdf_result = await read_pdf_as_content_blocks(pdf_path, executor, supports_vision=False)
            if isinstance(pdf_result, str):
                text_parts.append(pdf_result)
        else:
            text_parts.append(f"[PDF file: {pdf_path}] (No workspace filesystem available)")

    for doc_path in document_paths:
        if executor is not None:
            doc_result = await read_document_as_text(doc_path, executor, excel_mode=excel_mode)
            text_parts.append(doc_result)
        else:
            text_parts.append(f"[Document: {doc_path}] (No workspace filesystem available)")

    for vid_path in video_paths:
        if executor is not None:
            vid_result = await read_video_as_content_blocks(
                vid_path,
                executor,
                supports_vision=supports_vision,
                supports_video=False,
                vision_fallback_model_cfg=vision_fallback_model_cfg,
            )
            if isinstance(vid_result, str):
                text_parts.append(vid_result)
        else:
            text_parts.append(f"[Video file: {vid_path}] (No workspace filesystem available)")


async def _dispatch_truncation_event(
    meta: dict[str, object],
    *,
    tool: str,
    config: RunnableConfig,
) -> None:
    from myrm_agent_harness.utils.event_utils import dispatch_custom_event

    await dispatch_custom_event(
        "agent_status",
        {"event": "tool_truncated", "tool": tool, "metadata": meta},
        config=config,
    )


async def _read_via_service(
    path_str: str,
    executor: CodeExecutor | None,
    skills: list[SkillMetadata] | None,
    reason: str | None,
    *,
    is_dir: bool = False,
    config: RunnableConfig,
) -> str:
    op_context = OperationContext(
        operation=OperationType.VIEW,
        executor=executor,
        skills=skills or [],
        paths=[path_str],
        reason=reason,
    )
    service = FileOperationService(op_context)
    raw_out = await service.execute()
    truncated_text, was_truncated, meta = truncate_file_output(raw_out, is_dir=is_dir, path_str=path_str)
    if was_truncated:
        await _dispatch_truncation_event(meta, tool="file_read" if not is_dir else "list_dir", config=config)
    return truncated_text


async def process_text_paths(
    text_paths: list[str],
    executor: CodeExecutor | None,
    skills: list[SkillMetadata] | None,
    reason: str | None,
    mode: str,
    chunk_size_mb: int,
    *,
    config: RunnableConfig,
) -> list[str]:
    """Read plain text paths with preview/stream/all modes and truncation."""
    text_content_parts: list[str] = []

    for path_str in text_paths:
        base_path_str = path_base(path_str)

        if ":" in path_str or not executor:
            text_content_parts.append(
                await _read_via_service(path_str, executor, skills, reason, config=config)
            )
            continue

        try:
            if base_path_str.startswith("/mcp/"):
                text_content_parts.append(
                    await _read_via_service(path_str, executor, skills, reason, config=config)
                )
                continue

            workspace_path = Path(base_path_str)
            if not workspace_path.is_absolute():
                cwd = Path(executor.workspace_path) if executor else Path.cwd()
                workspace_path = cwd / workspace_path

            if not workspace_path.exists() or workspace_path.is_dir():
                text_content_parts.append(
                    await _read_via_service(
                        path_str,
                        executor,
                        skills,
                        reason,
                        is_dir=workspace_path.is_dir(),
                        config=config,
                    )
                )
                continue

            file_size_mb = workspace_path.stat().st_size / (1024 * 1024)
            effective_mode = mode
            if file_size_mb > 100 and mode == "all":
                effective_mode = "preview"
                logger.warning(
                    "File %s is %.1fMB (>100MB). Auto-fallback to preview mode to prevent OOM.",
                    base_path_str,
                    file_size_mb,
                )

            if effective_mode == "preview":
                content = await read_file_preview(workspace_path)
                text_content_parts.append(f"=== {base_path_str} (preview mode) ===\n{content}")
            elif effective_mode == "stream":
                content = await read_file_chunked(workspace_path, chunk_size_mb=chunk_size_mb)
                text_content_parts.append(f"=== {base_path_str} ===\n{content}")
            else:
                text_content_parts.append(
                    await _read_via_service(path_str, executor, skills, reason, config=config)
                )

        except Exception as e:
            logger.exception("Error processing %s with mode=%s: %s", path_str, mode, e)
            text_content_parts.append(
                await _read_via_service(path_str, executor, skills, reason, config=config)
            )

    return text_content_parts
