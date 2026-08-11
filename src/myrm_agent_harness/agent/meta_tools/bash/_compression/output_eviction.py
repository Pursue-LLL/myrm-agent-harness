"""即时大输出 eviction 模块

在 bash 工具返回时即时处理大输出：
1. 将完整输出保存到 .context/{chat_id}/evicted/ （统一清理体系）
2. 替换为智能预览 + 文件路径引用
3. 返回结构化结果供 SSE 事件携带 evicted 文件引用

与 FilterProcessor 的关系：
- 本模块是第一道防线（即时，只处理 bash_code_execute_tool 输出）
- FilterProcessor 是第二道防线（延迟，处理所有 ToolMessage）
- 两者独立，不冲突（eviction 后内容很小，FilterProcessor 自动跳过）

[INPUT]
- agent.context_management.infra.evicted_content::build_delivery_footer (POS: evicted 文件 footer 读取指令)
- agent.context_management.strategies.filter::should_filter (POS: token 阈值判定)
- agent.context_management.strategies.filters.base::STRUCTURAL_CONTENT_TYPES, FilterContext, detect_content_type (POS: 内容类型检测)
- agent.context_management.strategies.filters.structural_filter::StructuralFilter (POS: JSON XML CSV)
- .constants::BASH_OUTPUT_MAX_CHARS (POS: 字符阈值，与格式层硬截断对齐)
- toolkits.code_execution.executors.base::CodeExecutor (POS: Code executor base classes.)

[OUTPUT]
- maybe_evict_large_output: 大输出即时落盘 + 智能预览替换（stdout/stderr 通用）
- EvictionResult: Structured result with preview text and optional evicted file reference.
- EVICTION_BANNER_PREFIX (POS: eviction preview banner 前缀，供 output_compressor 跳过二次压缩)

[POS]
Provides maybe_evict_large_output and EvictionResult. Used for both stdout and
stderr streams (execute_mixin evicts them symmetrically); each
stream persists to its own evicted file and carries an independent GUI ref.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.context_management.infra.evicted_content import (
    build_delivery_footer,
)
from myrm_agent_harness.agent.context_management.strategies.filter import should_filter
from myrm_agent_harness.agent.context_management.strategies.filters.base import (
    STRUCTURAL_CONTENT_TYPES,
    FilterContext,
    detect_content_type,
)
from myrm_agent_harness.agent.context_management.strategies.filters.structural_filter import (
    StructuralFilter,
)
from myrm_agent_harness.agent.meta_tools.bash._compression.constants import (
    BASH_OUTPUT_MAX_CHARS,
)
from myrm_agent_harness.utils.text_utils import get_token_count, smart_truncate

if TYPE_CHECKING:
    from myrm_agent_harness.agent.context_management.infra.evicted_content import (
        EvictedPersistResult,
    )
    from myrm_agent_harness.toolkits.code_execution.executors.base import CodeExecutor

logger = logging.getLogger(__name__)

_PREVIEW_MAX_CHARS = 3000
_structural_filter = StructuralFilter()

# Banner prefix for every eviction preview. output_compressor uses the same
# constant to detect eviction previews and skip re-compression, so the preview
# and its file_read_tool read-back footer always survive the format pipeline.
EVICTION_BANNER_PREFIX = "[LARGE OUTPUT TRUNCATED ("


@dataclass(frozen=True, slots=True)
class EvictionResult:
    """Structured result from output eviction.

    Attributes:
        text: The preview text (or original content if no eviction occurred).
        evicted_ref: Filename of the evicted output file (basename only, e.g. "output_a3f5c8d1.txt").
                     None when output was not evicted.
    """

    text: str
    evicted_ref: str | None = None
    stored_chars: int | None = None
    total_lines: int | None = None
    storage_truncated: bool = False


async def maybe_evict_large_output(
    content: str, executor: CodeExecutor | None = None
) -> EvictionResult:
    """大输出截断为智能预览，可选持久化到沙箱文件

    触发条件（任一满足）：token 数超过 FILTER_TOKEN_THRESHOLD，或字符数超过
    BASH_OUTPUT_MAX_CHARS。字符口径与格式化层硬截断阈值对齐，
    保证所有会被格式层硬截断的输出都先落盘可读，避免中间数据不可达。
    stdout 与 stderr 两条流共用本函数（execute_mixin 对称调用）。

    Args:
        content: 清理后的流内容（stdout 或 stderr）
        executor: 沙箱执行器（提供时将大输出保存到文件）

    Returns:
        EvictionResult with preview text and optional evicted file reference.
    """
    if not should_filter(content) and len(content) <= BASH_OUTPUT_MAX_CHARS:
        return EvictionResult(text=content)

    file_path: str | None = None
    persist_stats: EvictedPersistResult | None = None
    try:
        if executor is not None:
            file_path, persist_stats = await _save_to_file(executor, content)
    except Exception as e:
        logger.warning(" [Eviction] Failed to save to file: %s", e)

    try:
        content_type = detect_content_type(content)

        if content_type in STRUCTURAL_CONTENT_TYPES:
            result = await _structural_filter.filter(
                FilterContext(content=content, file_path="", content_type=content_type)
            )
            preview = (
                f"[LARGE OUTPUT TRUNCATED ({result.total_lines} lines, ~{result.estimated_tokens} tokens)]\n\n"
                f"{result.summary}\n\n"
                f"{result.structure_overview}\n"
            )
            # Structural summary has no line mapping to the source; do not
            # derive a read offset so the footer falls back to a plain read.
            footer_head: str | None = None
        else:
            preview = _create_smart_preview(content)
            footer_head = _footer_head_part(preview)

        if file_path:
            preview += build_delivery_footer(
                evicted_basename=os.path.basename(file_path),
                head_text=footer_head,
                rel_path=file_path,
            )

        evicted_ref = os.path.basename(file_path) if file_path else None
        logger.warning(
            " [Eviction] Truncated to preview=%d chars, file=%s",
            len(preview),
            file_path,
        )
        return EvictionResult(
            text=preview,
            evicted_ref=evicted_ref,
            stored_chars=persist_stats.stored_chars if persist_stats else None,
            total_lines=persist_stats.total_lines if persist_stats else None,
            storage_truncated=(
                persist_stats.storage_truncated if persist_stats else False
            ),
        )

    except Exception as e:
        logger.warning(" [Eviction] Failed: %s, falling back to smart_truncate", e)
        fallback = _create_smart_preview(content)
        if file_path:
            fallback += build_delivery_footer(
                evicted_basename=os.path.basename(file_path),
                head_text=_footer_head_part(fallback),
                rel_path=file_path,
            )
        evicted_ref = os.path.basename(file_path) if file_path else None
        return EvictionResult(
            text=fallback,
            evicted_ref=evicted_ref,
            stored_chars=persist_stats.stored_chars if persist_stats else None,
            total_lines=persist_stats.total_lines if persist_stats else None,
            storage_truncated=(
                persist_stats.storage_truncated if persist_stats else False
            ),
        )


async def _save_to_file(
    executor: CodeExecutor, content: str
) -> tuple[str | None, EvictedPersistResult | None]:
    """Persist large bash output under `.context/{chat_id}/evicted/`.

    Uses the same workspace_root_var + chat_id_var path as web_fetch UECD spill
    (evicted_content.persist_evicted_content), not hardcoded /persistent paths.

    Returns None when no session context exists (preview-only, no GUI ref).
    """
    _ = executor  # Kept for call-site compatibility; persist uses workspace_root_var.
    session_id = _get_session_id()
    if not session_id:
        logger.warning("[Eviction] No session_id; skip file persist (preview only)")
        return None

    from myrm_agent_harness.agent.context_management.infra.evicted_content import (
        persist_evicted_content,
    )

    result = await persist_evicted_content(content, source="output", ext="txt")
    if result.evicted_ref and result.rel_path:
        return result.rel_path, result
    return None, None


def _create_smart_preview(content: str) -> str:
    """使用 smart_truncate 创建智能预览，自动检测尾部诊断信息"""
    lines = content.splitlines()
    total_lines = len(lines)
    estimated_tokens = get_token_count(content)

    truncated = smart_truncate(content, _PREVIEW_MAX_CHARS)
    return f"[LARGE OUTPUT TRUNCATED ({total_lines} lines, ~{estimated_tokens} tokens)]\n\n{truncated}"


def _footer_head_part(preview: str) -> str | None:
    """Extract the previewed source head from a smart-truncate preview.

    Returns ``None`` when the preview has no truncation marker (nothing was
    omitted), so ``build_delivery_footer`` falls back to a plain read.
    The preview banner line (e.g. ``[LARGE OUTPUT TRUNCATED (N lines...)]``)
    is a formatting artifact, not source content, so it is stripped to keep
    footer line numbers aligned with the evicted file.
    """
    if "[Truncated:" not in preview:
        return None
    head_text = preview.split("\n\n[Truncated:")[0]
    _, _, head = head_text.partition("\n")
    return head.lstrip("\n")


def _get_session_id() -> str | None:
    """Resolve active chat/session id for evicted file persistence."""
    try:
        from myrm_agent_harness.core.context_vars import chat_id_var

        chat_id = chat_id_var.get().strip()
        if chat_id:
            return chat_id
    except Exception:
        pass
    try:
        from myrm_agent_harness.agent.context_management.infra.session_lock import (
            get_current_chat_id,
        )

        return get_current_chat_id()
    except Exception:
        return None
