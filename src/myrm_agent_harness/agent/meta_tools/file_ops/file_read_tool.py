"""文件读取工具（Claude Code 兼容）

[INPUT]
- langchain.tools::tool (POS: LangChain 工具装饰器)
- core::FileOperationService, OperationContext, OperationType (POS: 文件操作服务)
- agent.security.redact::redact_sensitive_text (POS: 工具输出脱敏)
- backends.skills.types::SkillMetadata (POS: MCP 技能元数据)
- file_read_handlers::build_multimodal_result, append_media_text_parts, process_text_paths (POS: file_read 执行处理器)
- file_search.path_hint::suggest_similar_paths, format_path_not_found_hint (POS: 路径不存在时的相似路径提示)
- file_search.skill_path_filter::get_disabled_skill_roots, is_under_disabled_skill_root (POS: disabled skill 路径拦截)
- utils.vault_read::is_vault_uri, path_base, read_vault_paths_to_parts (POS: vault:// URI 读取)
- utils.*_reader (POS: 多模态与文档读取)
- utils.errors::ToolError (POS: 工具错误类型)

[OUTPUT]
- create_file_read_tool(): 工厂函数，创建 file_read_tool
- file_read_tool: LangChain Tool（本地/MCP/File ID/vault:// 路径、批量读取、行号范围、多模态、Office/Jupyter 解析）

[POS]
File read tool factory and orchestration. Heavy read logic lives in file_read_handlers.py.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING

from langchain.tools import tool
from langchain_core.messages.content import create_text_block
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field, field_validator

from myrm_agent_harness.agent.context_management.context import extract_context_from_runnable_config
from myrm_agent_harness.agent.security.redact import redact_sensitive_text
from myrm_agent_harness.toolkits.code_execution.executors.base import get_executor
from myrm_agent_harness.agent.meta_tools.file_search.path_hint import (
    format_path_not_found_hint,
    suggest_similar_paths,
)
from myrm_agent_harness.agent.meta_tools.file_search.skill_path_filter import (
    get_disabled_skill_roots,
    is_under_disabled_skill_root,
)
from myrm_agent_harness.utils.errors import ToolError

from .file_read_handlers import append_media_text_parts, build_multimodal_result, process_text_paths
from .utils.document_reader import is_document_path
from .utils.image_reader import is_image_path
from .utils.pdf_reader import is_pdf_path
from .utils.vault_read import is_vault_uri, path_base, read_vault_paths_to_parts
from .utils.video_reader import is_video_path

if TYPE_CHECKING:
    from langchain_core.tools import BaseTool

    from myrm_agent_harness.backends.skills.types import SkillMetadata

logger = logging.getLogger(__name__)

_URL_SCHEMES = ("http://", "https://", "ftp://", "ftps://")


def _is_url(path: str) -> bool:
    return path.lower().startswith(_URL_SCHEMES)


async def _assert_paths_allowed_for_read(
    paths: list[str],
    config: RunnableConfig,
    executor: object | None,
) -> None:
    disabled_roots = get_disabled_skill_roots(config)
    if not disabled_roots or executor is None:
        return
    resolve_path = getattr(executor, "resolve_path", None)
    if resolve_path is None:
        return
    for raw in paths:
        if is_vault_uri(raw) or _is_url(raw):
            continue
        base = path_base(raw)
        try:
            resolved = await resolve_path(base)
        except ValueError:
            resolved = base
        if is_under_disabled_skill_root(str(resolved), disabled_roots):
            raise ToolError(
                message=f"Path blocked: {raw}",
                user_hint="This path belongs to a disabled skill and cannot be read.",
            )


class FileReadInput(BaseModel):
    """文件读取工具输入参数"""

    paths: list[str] = Field(
        description=(
            "文件路径数组（必须是数组，不是字符串）。"
            "支持：本地文件、MCP 路径（/mcp/skill/function.md）、"
            "File ID（@file_001）、vault 指针（vault://uuid）、行号范围（file.py:1-50）、目录。"
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

    chunk_size_mb: int = Field(default=10, description="streaming模式下的块大小（MB），默认10MB")

    excel_mode: str | None = Field(
        default=None,
        description=(
            "Excel 文件专用读取模式（仅对 .xlsx/.xls 生效）：\n"
            "- None（默认）：小文件完整输出 Markdown 表格；大文件(>50KB)自动输出结构概览\n"
            "- 'content'：强制输出完整 Markdown 表格内容\n"
            "- 'structure'：仅输出 JSON 结构元数据（sheet名/行列数/列头/公式分布）\n"
            "- 'audit'：输出 JSON 公式错误审计报告"
        ),
    )

    reason: str | None = Field(default=None, description="执行命令的原因（可选，用于日志）")

    preserve_in_context: bool = Field(
        default=False,
        description="如果为 true，读取的内容将被打上保护标签，在长对话压缩时不会被遗忘。仅对核心规范、技能文件等极其重要的内容使用。",
    )

    @field_validator("paths", mode="before")
    @classmethod
    def normalize_paths(cls, v: list[str] | str | None) -> list[str] | None:
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
            return [v]
        return None


def create_file_read_tool(skills: list[SkillMetadata] | None = None) -> BaseTool:
    """创建 file_read_tool（详见 file_read_handlers 与 FileOperationService）。"""

    @tool(
        "file_read_tool",
        description="""读取文件内容或目录列表。支持图片（png/jpg/gif/webp）、PDF、Office 文档（docx/xlsx/xls）和 Jupyter Notebook（ipynb）。
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
  - `["analysis.ipynb"]` - 读取 Jupyter Notebook（自动提取 Markdown/Code cells）
  - `["vault://<uuid>"]` - 读取 auto-vault 落盘的大结果（子 Agent 返回的 vault 指针）
  - `["vault://<uuid>:1-50"]` - 读取 vault 对象指定行范围
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
        excel_mode: str | None = None,
        reason: str | None = None,
        preserve_in_context: bool = False,
        *,
        config: RunnableConfig,
    ) -> str | Sequence[object]:
        valid_paths: list[str] = []
        try:
            url_paths = [p for p in paths if _is_url(p)]
            valid_paths = [p for p in paths if not _is_url(p)]

            url_errors: list[str] = []
            if url_paths:
                rejected = ", ".join(url_paths[:3])
                suffix = f" (and {len(url_paths) - 3} more)" if len(url_paths) > 3 else ""
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
            await _assert_paths_allowed_for_read(valid_paths, config, executor)
            supports_vision = bool(ctx.get("supports_vision", False))
            vision_fallback_model_cfg = ctx.get("vision_fallback_model_cfg")

            image_paths = [p for p in valid_paths if is_image_path(path_base(p)) and not is_vault_uri(p)]
            pdf_paths = [p for p in valid_paths if is_pdf_path(path_base(p)) and not is_vault_uri(p)]
            document_paths = [p for p in valid_paths if is_document_path(path_base(p)) and not is_vault_uri(p)]
            video_paths = [p for p in valid_paths if is_video_path(path_base(p)) and not is_vault_uri(p)]
            vault_paths = [p for p in valid_paths if is_vault_uri(p)]
            text_paths = [
                p
                for p in valid_paths
                if not is_vault_uri(p)
                and not is_image_path(path_base(p))
                and not is_pdf_path(path_base(p))
                and not is_document_path(path_base(p))
                and not is_video_path(path_base(p))
            ]

            has_multimodal = (image_paths or pdf_paths or video_paths) and executor is not None
            use_multimodal = has_multimodal and (supports_vision or vision_fallback_model_cfg is not None)
            has_documents = bool(document_paths) and executor is not None

            if (use_multimodal or has_documents) and executor is not None:
                blocks = await build_multimodal_result(
                    image_paths,
                    pdf_paths,
                    document_paths,
                    text_paths,
                    vault_paths,
                    executor,
                    skills,
                    reason,
                    url_errors,
                    supports_vision=supports_vision,
                    vision_fallback_model_cfg=vision_fallback_model_cfg,
                    video_paths=video_paths,
                    excel_mode=excel_mode,
                    mode=mode,
                    config=config,
                )
                if preserve_in_context:
                    blocks.insert(0, create_text_block("<preserve_context>\n"))
                    blocks.append(create_text_block("\n</preserve_context>"))
                return blocks

            text_parts: list[str] = list(url_errors)
            await append_media_text_parts(
                text_parts,
                image_paths=image_paths,
                pdf_paths=pdf_paths,
                document_paths=document_paths,
                video_paths=video_paths,
                executor=executor,
                supports_vision=supports_vision,
                vision_fallback_model_cfg=vision_fallback_model_cfg,
                excel_mode=excel_mode,
            )

            if vault_paths:
                text_parts.extend(await read_vault_paths_to_parts(vault_paths, executor, mode, config=config))

            if text_paths:
                text_parts.extend(
                    await process_text_paths(
                        text_paths,
                        executor,
                        skills,
                        reason,
                        mode,
                        chunk_size_mb,
                        config=config,
                    )
                )

            result = "\n\n".join(text_parts) if text_parts else "No results."
            final_text = redact_sensitive_text(result)
            if preserve_in_context:
                final_text = f"<preserve_context>\n{final_text}\n</preserve_context>"
            return final_text

        except ToolError:
            raise
        except FileNotFoundError as e:
            hint_path = path_base(valid_paths[0]) if valid_paths else str(e)
            suggestions = suggest_similar_paths(hint_path)
            raise ToolError(
                message=str(e),
                user_hint=format_path_not_found_hint(hint_path, suggestions),
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
            logger.exception("Unexpected error in file_read_tool: %s", e)
            raise ToolError(
                message=f"Unexpected error during file read: {e}",
                user_hint="An unexpected error occurred. Please try again or check the file path.",
            ) from e

    return file_read_func
