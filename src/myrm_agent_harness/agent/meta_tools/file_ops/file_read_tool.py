"""文件读取工具（Claude Code 兼容）

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- langchain.tools::tool (POS: LangChain 工具装饰器)
- core::FileOperationService, OperationContext, OperationType (POS: 文件操作服务，提供统一的文件操作接口)
- agent.security.redact::redact_sensitive_text (POS: 工具输出脱敏，防止凭证泄露到 LLM 上下文)
- backends.skills.types::SkillMetadata (POS: 技能元数据，提供 MCP 虚拟路径支持)
- utils.image_reader::is_image_path, read_image_as_content_blocks (POS: 图片文件多模态读取)
- utils.video_reader::is_video_path, read_video_as_content_blocks (POS: 视频文件多模态读取，支持直传/帧提取降级)
- utils.pdf_reader::is_pdf_path, read_pdf_as_content_blocks (POS: PDF 文件智能读取，文本优先 + 图片回退)
- utils.document_reader::is_document_path, read_document_as_text (POS: Office 文档读取，docx/xlsx/xls 转 Markdown)
- utils.errors::ToolError (POS: 工具错误类型)

[OUTPUT]
- create_file_read_tool(): 工厂函数，创建 file_read_tool
- file_read_tool: LangChain Tool（读取文件内容，支持 MCP 路径、File ID、批量读取、行号范围、目录列表、图片/PDF 多模态、Office 文档解析）

[POS]
File read tool (Claude Code compatible). Supports multiple path formats (local, MCP, File ID), batch concurrent reads, line ranges, multimodal image reading for vision models, and Office document parsing (docx/xlsx/xls → Markdown).

"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from langchain.tools import tool
from langchain_core.messages.content import ContentBlock, create_text_block
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, field_validator

from myrm_agent_harness.agent.context_management.context import (
    extract_context_from_runnable_config,
)
from myrm_agent_harness.agent.security.redact import redact_sensitive_text
from myrm_agent_harness.toolkits.code_execution.executors.base import get_executor
from myrm_agent_harness.utils.errors import ToolError

from .core import FileOperationService, OperationContext, OperationType
from .streaming import read_file_chunked, read_file_preview
from .utils.document_reader import is_document_path, read_document_as_text
from .utils.image_reader import is_image_path, read_image_as_content_blocks
from .utils.pdf_reader import is_pdf_path, read_pdf_as_content_blocks
from .utils.video_reader import is_video_path, read_video_as_content_blocks

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.backends.skills.types import SkillMetadata
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

logger = logging.getLogger(__name__)

_URL_SCHEMES = ("http://", "https://", "ftp://", "ftps://")


def _is_url(path: str) -> bool:
    """Check if a path is a URL rather than a local file path."""
    return path.lower().startswith(_URL_SCHEMES)


def _truncate_file_output(
    output: str, max_chars: int = 10000, is_dir: bool = False, path_str: str = "file"
) -> tuple[str, bool, dict]:
    """Smart head-truncation for file/ls output with pagination hint."""
    if len(output) <= max_chars:
        return output, False, {}
    head = output[:max_chars]

    if is_dir:
        hint = "[truncated... Use a more specific path to view fewer items]"
        return f"{head}\n\n...{hint}", True, {"type": "dir", "path": path_str}
    else:
        total_lines = output.count("\n") + 1
        total_mb = len(output.encode("utf-8", errors="ignore")) / (1024 * 1024)

        hint = f"[SYSTEM WARNING: File is extremely large ({total_mb:.2f}MB, {total_lines} lines). Output has been TRUNCATED at {max_chars} chars. You are ONLY seeing the top portion. Use start_line/end_line syntax (e.g. {path_str}:100-200) to read specific sections.]"

        metadata = {
            "type": "file",
            "path": path_str,
            "total_lines": total_lines,
            "total_mb": round(total_mb, 2),
            "shown_chars": max_chars,
        }
        return f"{head}\n\n...{hint}", True, metadata


class FileReadInput(BaseModel):
    """文件读取工具输入参数"""

    paths: list[str] = Field(
        description=(
            "文件路径数组（必须是数组，不是字符串）。"
            "支持：本地文件、MCP 路径（/mcp/skill/function.md）、"
            "File ID（@file_001）、行号范围（file.py:1-50）、目录。"
            "不支持 URL（http/https），仅支持本地文件路径！"
            "禁止凭空编造不存在的路径！"
        )
    )

    mode: str = Field(
        default="all",
        description=(
            "读取模式：\n"
            "- 'all'（默认）：完整读取文件（<10MB推荐）\n"
            "- 'preview'：仅读取前1000行 + 显示总行数（大文件快速预览）\n"
            "- 'stream'：分块流式读取（>100MB文件推荐，防止内存溢出）"
        ),
    )

    chunk_size_mb: int = Field(
        default=10, description="streaming模式下的块大小（MB），默认10MB"
    )

    reason: str | None = Field(
        default=None, description="执行命令的原因（可选，用于日志）"
    )

    preserve_in_context: bool = Field(
        default=False,
        description="如果为 true，读取的内容将被打上保护标签，在长对话压缩时不会被遗忘。仅对核心规范、技能文件等极其重要的内容使用。"
    )

    @field_validator("paths", mode="before")
    @classmethod
    def normalize_paths(cls, v: list[str] | str | None) -> list[str] | None:
        """规范化 paths 参数，兼容模型传递字符串格式的 JSON

        处理 LLM 常见错误：
        - 传递 "[\"file.py\"]" 而非 ["file.py"]
        - 传递单个字符串而非数组
        """
        if v is None:
            return None
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass
            # 如果不是 JSON 列表，当作单个路径
            return [v]
        return None


async def _build_multimodal_result(
    image_paths: list[str],
    pdf_paths: list[str],
    document_paths: list[str],
    text_paths: list[str],
    executor: CodeExecutor,
    skills: list[SkillMetadata] | None,
    reason: str | None,
    url_errors: list[str],
    supports_vision: bool,
    vision_fallback_model_cfg: object | None = None,
    video_paths: list[str] | None = None,
) -> list[ContentBlock]:
    """Build multimodal result: images/PDFs as content blocks, documents/text as text blocks"""
    blocks: list[ContentBlock] = []

    if url_errors:
        blocks.append(create_text_block("\n".join(url_errors)))

    for img_path in image_paths:
        if supports_vision:
            result = await read_image_as_content_blocks(
                img_path, executor, supports_vision=True
            )
            if isinstance(result, list):
                blocks.extend(result)
            else:
                blocks.append(create_text_block(result))
        elif vision_fallback_model_cfg:
            from myrm_agent_harness.agent.config.llm import LLMConfig
            from myrm_agent_harness.toolkits.vision.fallback_engine import (
                VisionFallbackEngine,
            )

            try:
                fallback_config = LLMConfig.model_validate(
                    vision_fallback_model_cfg, from_attributes=True
                )
                fallback_text = await VisionFallbackEngine(
                    fallback_config
                ).describe_local_image(img_path, executor)
                blocks.append(
                    create_text_block(
                        f"[Image Analysis for {img_path}]:\n{fallback_text}"
                    )
                )
            except Exception as e:
                logger.warning(f"Vision fallback failed for {img_path}: {e}")
                blocks.append(
                    create_text_block(
                        f"[Image file: {img_path}] (Vision fallback failed: {e})"
                    )
                )
        else:
            result = await read_image_as_content_blocks(
                img_path, executor, supports_vision=False
            )
            if isinstance(result, list):
                blocks.extend(result)
            else:
                blocks.append(create_text_block(result))

    for pdf_path in pdf_paths:
        result = await read_pdf_as_content_blocks(
            pdf_path, executor, supports_vision=supports_vision
        )
        if isinstance(result, list):
            blocks.extend(result)
        else:
            blocks.append(create_text_block(result))

    for doc_path in document_paths:
        result = await read_document_as_text(doc_path, executor)
        blocks.append(create_text_block(result))

    for vid_path in (video_paths or []):
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


def create_file_read_tool(skills: list[SkillMetadata] | None = None) -> BaseTool:
    """创建文件读取工具

    内部使用 FileOperationService，自动处理：
    - MCP 虚拟路径（/mcp/ 路径通过 skills 读取）
    - File ID 解析（@file_001 → 实际路径）
    - 批量并发读取（支持多个路径）
    - 目录列表（自动检测目录）
    - Skill 文档特殊处理
    - ArtifactTracker 通知
    - 策略自动选择（MCPFileSystemStrategy / StorageBackendStrategy）

    Args:
        skills: MCP 技能列表（用于 /mcp/ 路径读取）

    Returns:
        file_read_tool 工具函数

    Note:
        StorageProvider 通过 context 注入，不再通过参数传递
    """

    @tool(
        "file_read_tool",
        description="""读取文件内容或目录列表。支持图片（png/jpg/gif/webp）、PDF 和 Office 文档（docx/xlsx/xls）。
参数：
- paths: 文件路径数组。支持行号范围语法：
  - `["file.py"]` - 读取整个文件
  - `["file.py:1-50"]` - 读取第 1-50 行
  - `["file.py:100-"]` - 从第 100 行读取到文件末尾
  - `["src/"]` - 读取目录下的所有文件
  - `["chart.png"]` - 读取图片（返回可视内容）
  - `["report.pdf"]` - 读取 PDF（返回文档内容，支持图表/表格识别）
  - `["contract.docx"]` - 读取 Word 文档（自动转为 Markdown）
  - `["data.xlsx"]` - 读取 Excel 文件（自动转为 Markdown 表格）
- mode: 读取模式（'all'默认 | 'preview'快速预览 | 'stream'大文件防OOM）
  - **大文件建议**：>100MB文件使用mode='preview'快速查看，或使用行号范围读取指定部分
- chunk_size_mb: streaming块大小（默认10MB）

**注意**: 必须是 JSON 数组，不是字符串！禁止凭空编造不存在的路径！
**不支持 URL（http/https）**：此工具仅读取本地文件，不能访问网页 URL。
""",
        args_schema=FileReadInput,
    )
    async def file_read_func(
        paths: list[str],
        mode: str = "all",
        chunk_size_mb: int = 10,
        reason: str | None = None,
        preserve_in_context: bool = False,
        *,
        config: RunnableConfig,
    ) -> str | Sequence[object]:
        """读取文件内容（文本文件返回 str，图片/PDF 文件返回 LangChain content blocks）"""
        try:
            url_paths = [p for p in paths if _is_url(p)]
            valid_paths = [p for p in paths if not _is_url(p)]

            url_errors: list[str] = []
            if url_paths:
                rejected = ", ".join(url_paths[:3])
                suffix = (
                    f" (and {len(url_paths) - 3} more)" if len(url_paths) > 3 else ""
                )
                url_errors.append(
                    f"file_read_tool cannot read URLs: {rejected}{suffix}. "
                    "This tool only supports local file paths, not web URLs."
                )

            if not valid_paths:
                if url_errors:
                    return "\n".join(url_errors)
                raise ValueError("No valid paths provided.")

            ctx = extract_context_from_runnable_config(config)
            executor = get_executor()
            supports_vision = bool(ctx.get("supports_vision", False))
            vision_fallback_model_cfg = ctx.get("vision_fallback_model_cfg")

            image_paths = [
                p.split(":")[0] for p in valid_paths if is_image_path(p.split(":")[0])
            ]
            pdf_paths = [
                p.split(":")[0] for p in valid_paths if is_pdf_path(p.split(":")[0])
            ]
            document_paths = [
                p.split(":")[0]
                for p in valid_paths
                if is_document_path(p.split(":")[0])
            ]
            video_paths = [
                p.split(":")[0] for p in valid_paths if is_video_path(p.split(":")[0])
            ]
            text_paths = [
                p
                for p in valid_paths
                if not is_image_path(p.split(":")[0])
                and not is_pdf_path(p.split(":")[0])
                and not is_document_path(p.split(":")[0])
                and not is_video_path(p.split(":")[0])
            ]

            has_multimodal = (image_paths or pdf_paths or video_paths) and executor is not None
            use_multimodal = has_multimodal and (
                supports_vision or vision_fallback_model_cfg is not None
            )

            has_documents = bool(document_paths) and executor is not None
            if (use_multimodal or has_documents) and executor is not None:
                blocks = await _build_multimodal_result(
                    image_paths,
                    pdf_paths,
                    document_paths,
                    text_paths,
                    executor,
                    skills,
                    reason,
                    url_errors,
                    supports_vision=supports_vision,
                    vision_fallback_model_cfg=vision_fallback_model_cfg,
                    video_paths=video_paths,
                )
                if preserve_in_context:
                    blocks.insert(0, create_text_block("<preserve_context>\n"))
                    blocks.append(create_text_block("\n</preserve_context>"))
                return blocks

            text_parts: list[str] = list(url_errors)

            for img_path in image_paths:
                if executor is not None:
                    if supports_vision:
                        img_result = await read_image_as_content_blocks(
                            img_path, executor, supports_vision=True
                        )
                        if isinstance(img_result, str):
                            text_parts.append(img_result)
                    elif vision_fallback_model_cfg:
                        from myrm_agent_harness.agent.config.llm import LLMConfig
                        from myrm_agent_harness.toolkits.vision.fallback_engine import (
                            VisionFallbackEngine,
                        )

                        try:
                            fallback_config = LLMConfig.model_validate(
                                vision_fallback_model_cfg, from_attributes=True
                            )
                            fallback_text = await VisionFallbackEngine(
                                fallback_config
                            ).describe_local_image(img_path, executor)
                            text_parts.append(
                                f"[Image Analysis for {img_path}]:\n{fallback_text}"
                            )
                        except Exception as e:
                            logger.warning(
                                f"Vision fallback failed for {img_path}: {e}"
                            )
                            text_parts.append(
                                f"[Image file: {img_path}] (Vision fallback failed: {e})"
                            )
                    else:
                        img_result = await read_image_as_content_blocks(
                            img_path, executor, supports_vision=False
                        )
                        if isinstance(img_result, str):
                            text_parts.append(img_result)
                else:
                    text_parts.append(
                        f"[Image file: {img_path}] (No workspace filesystem available)"
                    )

            for pdf_path in pdf_paths:
                if executor is not None:
                    pdf_result = await read_pdf_as_content_blocks(
                        pdf_path, executor, supports_vision=False
                    )
                    if isinstance(pdf_result, str):
                        text_parts.append(pdf_result)
                else:
                    text_parts.append(
                        f"[PDF file: {pdf_path}] (No workspace filesystem available)"
                    )

            for doc_path in document_paths:
                if executor is not None:
                    doc_result = await read_document_as_text(doc_path, executor)
                    text_parts.append(doc_result)
                else:
                    text_parts.append(
                        f"[Document: {doc_path}] (No workspace filesystem available)"
                    )

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
                    text_parts.append(
                        f"[Video file: {vid_path}] (No workspace filesystem available)"
                    )

            if text_paths:
                # [A] 处理 streaming/preview 模式（大文件防OOM）
                text_content_parts: list[str] = []

                for path_str in text_paths:
                    # 解析路径（移除行号范围）
                    base_path_str = (
                        path_str.split(":")[0] if ":" in path_str else path_str
                    )

                    # 如果是目录或有行号范围，使用原逻辑
                    if ":" in path_str or not executor:
                        # 使用原逻辑（FileOperationService）
                        op_context = OperationContext(
                            operation=OperationType.VIEW,
                            executor=executor,
                            skills=skills or [],
                            paths=[path_str],
                            reason=reason,
                        )
                        service = FileOperationService(op_context)
                        raw_out = await service.execute()
                        truncated_text, was_truncated, meta = _truncate_file_output(
                            raw_out, path_str=path_str
                        )
                        text_content_parts.append(truncated_text)
                        if was_truncated:
                            from myrm_agent_harness.utils.event_utils import (
                                dispatch_custom_event,
                            )

                            await dispatch_custom_event(
                                "agent_status",
                                {
                                    "event": "tool_truncated",
                                    "tool": "file_read",
                                    "metadata": meta,
                                },
                                config=config,
                            )
                        continue

                    # [B] 检查文件大小（仅本地文件，非MCP路径）
                    try:
                        from pathlib import Path

                        if base_path_str.startswith("/mcp/"):
                            # MCP路径，使用原逻辑
                            op_context = OperationContext(
                                operation=OperationType.VIEW,
                                executor=executor,
                                skills=skills or [],
                                paths=[path_str],
                                reason=reason,
                            )
                            service = FileOperationService(op_context)
                            raw_out = await service.execute()
                            truncated_text, was_truncated, meta = _truncate_file_output(
                                raw_out, path_str=path_str
                            )
                            text_content_parts.append(truncated_text)
                            if was_truncated:
                                from myrm_agent_harness.utils.event_utils import (
                                    dispatch_custom_event,
                                )

                                await dispatch_custom_event(
                                    "agent_status",
                                    {
                                        "event": "tool_truncated",
                                        "tool": "file_read",
                                        "metadata": meta,
                                    },
                                    config=config,
                                )
                            continue

                        # [C] 自动fallback：>100MB强制preview
                        workspace_path = Path(base_path_str)
                        if not workspace_path.is_absolute():
                            # 相对路径，转为绝对路径
                            cwd = (
                                Path(executor.workspace_path)
                                if executor
                                else Path.cwd()
                            )
                            workspace_path = cwd / workspace_path

                        if not workspace_path.exists():
                            # 文件不存在，交给原逻辑处理错误
                            op_context = OperationContext(
                                operation=OperationType.VIEW,
                                executor=executor,
                                skills=skills or [],
                                paths=[path_str],
                                reason=reason,
                            )
                            service = FileOperationService(op_context)
                            raw_out = await service.execute()
                            truncated_text, was_truncated, meta = _truncate_file_output(
                                raw_out, path_str=path_str
                            )
                            text_content_parts.append(truncated_text)
                            if was_truncated:
                                from myrm_agent_harness.utils.event_utils import (
                                    dispatch_custom_event,
                                )

                                await dispatch_custom_event(
                                    "agent_status",
                                    {
                                        "event": "tool_truncated",
                                        "tool": "file_read",
                                        "metadata": meta,
                                    },
                                    config=config,
                                )
                            continue

                        if workspace_path.is_dir():
                            # 目录，使用原逻辑
                            op_context = OperationContext(
                                operation=OperationType.VIEW,
                                executor=executor,
                                skills=skills or [],
                                paths=[path_str],
                                reason=reason,
                            )
                            service = FileOperationService(op_context)
                            raw_out = await service.execute()
                            truncated_text, was_truncated, meta = _truncate_file_output(
                                raw_out, is_dir=True, path_str=path_str
                            )
                            text_content_parts.append(truncated_text)
                            if was_truncated:
                                from myrm_agent_harness.utils.event_utils import (
                                    dispatch_custom_event,
                                )

                                await dispatch_custom_event(
                                    "agent_status",
                                    {
                                        "event": "tool_truncated",
                                        "tool": "list_dir",
                                        "metadata": meta,
                                    },
                                    config=config,
                                )
                            continue

                        file_size_mb = workspace_path.stat().st_size / (1024 * 1024)

                        # [D] 自动fallback：>100MB强制preview
                        effective_mode = mode
                        if file_size_mb > 100 and mode == "all":
                            effective_mode = "preview"
                            logger.warning(
                                f"File {base_path_str} is {file_size_mb:.1f}MB (>100MB). "
                                f"Auto-fallback to preview mode to prevent OOM."
                            )

                        # [E] 应用 mode 逻辑
                        if effective_mode == "preview":
                            content = await read_file_preview(workspace_path)
                            text_content_parts.append(
                                f"=== {base_path_str} (preview mode) ===\n{content}"
                            )
                        elif effective_mode == "stream":
                            content = await read_file_chunked(
                                workspace_path, chunk_size_mb=chunk_size_mb
                            )
                            text_content_parts.append(
                                f"=== {base_path_str} ===\n{content}"
                            )
                        else:
                            # mode='all'，使用原逻辑
                            op_context = OperationContext(
                                operation=OperationType.VIEW,
                                executor=executor,
                                skills=skills or [],
                                paths=[path_str],
                                reason=reason,
                            )
                            service = FileOperationService(op_context)
                            raw_out = await service.execute()
                            is_dir = workspace_path.is_dir()
                            truncated_text, was_truncated, meta = _truncate_file_output(
                                raw_out, is_dir=is_dir, path_str=path_str
                            )
                            text_content_parts.append(truncated_text)
                            if was_truncated:
                                print(
                                    f" TRUNCATED FILE READ: {path_str} - dispatching agent_status"
                                )
                                from myrm_agent_harness.utils.event_utils import (
                                    dispatch_custom_event,
                                )

                                await dispatch_custom_event(
                                    "agent_status",
                                    {
                                        "event": "tool_truncated",
                                        "tool": "file_read",
                                        "metadata": meta,
                                    },
                                    config=config,
                                )

                    except Exception as e:
                        logger.exception(
                            f"Error processing {path_str} with mode={mode}: {e}"
                        )
                        # Fallback to original logic
                        op_context = OperationContext(
                            operation=OperationType.VIEW,
                            executor=executor,
                            skills=skills or [],
                            paths=[path_str],
                            reason=reason,
                        )
                        service = FileOperationService(op_context)
                        raw_out = await service.execute()
                        truncated_text, was_truncated, meta = _truncate_file_output(
                            raw_out, path_str=path_str
                        )
                        text_content_parts.append(truncated_text)
                        if was_truncated:
                            from myrm_agent_harness.utils.event_utils import (
                                dispatch_custom_event,
                            )

                            await dispatch_custom_event(
                                "agent_status",
                                {
                                    "event": "tool_truncated",
                                    "tool": "file_read",
                                    "metadata": meta,
                                },
                                config=config,
                            )

                text_parts.extend(text_content_parts)

            result = "\n\n".join(text_parts) if text_parts else "No results."
            final_text = redact_sensitive_text(result)
            if preserve_in_context:
                final_text = f"<preserve_context>\n{final_text}\n</preserve_context>"
            return final_text

        except ToolError:
            raise
        except FileNotFoundError as e:
            raise ToolError(
                message=str(e),
                user_hint="The file or directory does not exist. Please check the path and try again.",
            ) from e
        except PermissionError as e:
            raise ToolError(
                message=str(e),
                user_hint="Permission denied. You cannot perform this operation on this path.",
            ) from e
        except ValueError as e:
            raise ToolError(
                message=str(e),
                user_hint="Invalid parameter. Please check the file path format and try again.",
            ) from e
        except Exception as e:
            logger.exception(f"Unexpected error in file_read_tool: {e}")
            raise ToolError(
                message=f"Unexpected error during file read: {e}",
                user_hint="An unexpected error occurred. Please try again or check the file path.",
            ) from e

    return file_read_func
