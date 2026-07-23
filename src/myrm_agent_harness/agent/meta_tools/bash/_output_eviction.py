"""即时大输出 eviction 模块

在 bash 工具返回时即时处理大输出：
1. 将完整输出保存到 .context/{session_id}/evicted/ （统一清理体系）
2. 替换为智能预览 + 文件路径引用
3. 返回结构化结果供 SSE 事件携带 evicted 文件引用

与 FilterProcessor 的关系：
- 本模块是第一道防线（即时，只处理 bash_code_execute_tool 输出）
- FilterProcessor 是第二道防线（延迟，处理所有 ToolMessage）
- 两者独立，不冲突（eviction 后内容很小，FilterProcessor 自动跳过）

[INPUT]
- agent.context_management.strategies.filters.base::STRUCTURAL_CONTENT_TYPES, (POS: Provides FileOperationObserver.)
- agent.context_management.strategies.filters.structural_filter::StructuralFilter (POS: JSON XML CSV)
- toolkits.code_execution.executors.base::CodeExecutor (POS: Code executor base classes.)

[OUTPUT]
- maybe_evict_large_output: Args:
- EvictionResult: Structured result with preview text and optional evicted file reference.

[POS]
Provides maybe_evict_large_output and EvictionResult.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.context_management.infra.evicted_content import (
    build_delivery_footer,
    cap_content_for_storage,
)
from myrm_agent_harness.agent.context_management.strategies.filter import should_filter
from myrm_agent_harness.agent.context_management.strategies.filters.base import (
    STRUCTURAL_CONTENT_TYPES,
    FilterContext,
    detect_content_type,
)
from myrm_agent_harness.agent.context_management.strategies.filters.structural_filter import StructuralFilter
from myrm_agent_harness.utils.text_utils import get_token_count, smart_truncate

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

logger = logging.getLogger(__name__)

_PREVIEW_MAX_CHARS = 3000
_structural_filter = StructuralFilter()


@dataclass(frozen=True, slots=True)
class EvictionResult:
    """Structured result from output eviction.

    Attributes:
        text: The preview text (or original stdout if no eviction occurred).
        evicted_ref: Filename of the evicted output file (basename only, e.g. "output_a3f5c8d1.txt").
                     None when output was not evicted.
    """

    text: str
    evicted_ref: str | None = None


async def maybe_evict_large_output(stdout: str, executor: CodeExecutor | None = None) -> EvictionResult:
    """大输出截断为智能预览，可选持久化到沙箱文件

    Args:
        stdout: 清理后的标准输出
        executor: 沙箱执行器（提供时将大输出保存到文件）

    Returns:
        EvictionResult with preview text and optional evicted file reference.
    """
    if not should_filter(stdout):
        return EvictionResult(text=stdout)

    file_path: str | None = None
    try:
        if executor is not None:
            file_path = await _save_to_file(executor, stdout)
    except Exception as e:
        logger.warning(" [Eviction] Failed to save to file: %s", e)

    try:
        content_type = detect_content_type(stdout)

        if content_type in STRUCTURAL_CONTENT_TYPES:
            result = await _structural_filter.filter(
                FilterContext(content=stdout, file_path="", content_type=content_type)
            )
            preview = (
                f"[LARGE OUTPUT TRUNCATED ({result.total_lines} lines, ~{result.estimated_tokens} tokens)]\n\n"
                f"{result.summary}\n\n"
                f"{result.structure_overview}\n"
            )
        else:
            preview = _create_smart_preview(stdout)

        if file_path:
            head_part = preview.split("\n\n[Truncated:")[0] if "[Truncated:" in preview else preview
            preview += build_delivery_footer(
                evicted_basename=os.path.basename(file_path),
                head_text=head_part,
                rel_path=file_path,
            )

        evicted_ref = os.path.basename(file_path) if file_path else None
        logger.warning(" [Eviction] Truncated to preview=%d chars, file=%s", len(preview), file_path)
        return EvictionResult(text=preview, evicted_ref=evicted_ref)

    except Exception as e:
        logger.warning(" [Eviction] Failed: %s, falling back to smart_truncate", e)
        fallback = _create_smart_preview(stdout)
        if file_path:
            head_part = fallback.split("\n\n[Truncated:")[0] if "[Truncated:" in fallback else fallback
            fallback += build_delivery_footer(
                evicted_basename=os.path.basename(file_path),
                head_text=head_part,
                rel_path=file_path,
            )
        evicted_ref = os.path.basename(file_path) if file_path else None
        return EvictionResult(text=fallback, evicted_ref=evicted_ref)


async def _save_to_file(executor: CodeExecutor, content: str) -> str | None:
    """Persist large bash output under `.context/{session_id}/evicted/`.

    Returns None when no session context exists (preview-only, no GUI ref).
    """
    session_id = _get_session_id()
    if not session_id:
        logger.warning("[Eviction] No session_id; skip file persist (preview only)")
        return None

    from myrm_agent_harness.runtime.execution_paths import (
        ensure_context_dir_exists,
        get_evicted_output_path,
        get_workspace_relative_path,
    )

    abs_path = get_evicted_output_path(session_id)
    rel_path = get_workspace_relative_path(abs_path)
    ensure_context_dir_exists(session_id, "evicted")
    capped_content, _ = cap_content_for_storage(content)
    await executor.write_file(rel_path, capped_content)
    return rel_path


def _create_smart_preview(content: str) -> str:
    """使用 smart_truncate 创建智能预览，自动检测尾部诊断信息"""
    lines = content.splitlines()
    total_lines = len(lines)
    estimated_tokens = get_token_count(content)

    truncated = smart_truncate(content, _PREVIEW_MAX_CHARS)
    return f"[LARGE OUTPUT TRUNCATED ({total_lines} lines, ~{estimated_tokens} tokens)]\n\n{truncated}"


def _get_session_id() -> str | None:
    """尝试从 contextvars 获取当前 session_id"""
    try:
        from myrm_agent_harness.agent.context_management.infra.session_lock import get_current_chat_id

        return get_current_chat_id()
    except Exception:
        return None
