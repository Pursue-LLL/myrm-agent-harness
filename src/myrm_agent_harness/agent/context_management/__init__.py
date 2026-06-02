"""Context management module.

提供上下文过滤、压缩、摘要等功能，用于管理 Agent 的上下文窗口。

核心组件：
1. schemas: 紧凑格式和摘要模式定义
2. filter: 大型工具结果过滤（任务感知的混合过滤策略）
   - 结构化数据（JSON/XML/代码）：使用 StructuralFilter
   - 非结构化数据（HTML/Markdown/纯文本）：使用 SemanticFilter + LLM
3. compactor: 统一压缩逻辑（合并 Context Editing + Compact）
4. summarizer: 上下文摘要逻辑（最后手段）
5. filters: 过滤器子模块
   - StructuralFilter: 结构化数据过滤器
   - SemanticFilter: 语义过滤器（使用 LLM）
6. pipeline: Pipeline 架构的上下文处理
   - ContextPipeline: 管道引擎
   - 统一 builder: build_default_processors / create_default_pipeline
   - 处理器: ThinkingBlockCleaner, FilterProcessor, CompressProcessor,
     SessionNotesProcessor, SummarizeProcessor, ExplicitCacheProcessor

设计理念（来自 Manus + Anthropic）：
- 过滤 (Filtering) 是立即的：大结果截断 + 智能预览
- 压缩 (Compression)：三级策略（Dedup/Truncate/Remove）；通过 ContextCompressOffloadCallback 落盘后再紧凑化（Manus "有损但可追溯"原则）
  - 工具特定模板（保留标识符和元信息）
  - 最小清理保护（避免小清理破坏 Prompt Cache）
- 摘要 (Summarization) 是不可逆的：原始消息结构被替换，无法恢复
- 保留最近 N 次工具调用的完整格式，作为 few-shot 示例
"""

from .context import AgentContext
from .infra.archive_reference import ContextArchiveReference
from .infra.cache_policy import CacheTtlPrunePolicy, resolve_cache_ttl_prune_policy
from .infra.schemas import (
    BUILTIN_PROTECTED_TOOLS,
    DEFAULT_BUSINESS_PROTECTED_TOOLS,
    DEFAULT_CONTEXT_CONFIG,
    DEFAULT_SOFT_ONLY_TOOLS,
    TOOL_PROTECTION_CONFIG,
    CacheUsageFeedback,
    CompactToolCall,
    CompressionIntent,
    ContextCompressOffloadCallback,
    ContextConfig,
    ContextOffloadResult,
    ContextSnapshotCallback,
    StructuredSummary,
    ToolProtectionConfig,
    ToolPruneMode,
)
from .infra.session_lock import (
    acquire_context_lock,
    clear_all_locks,
    get_active_session_count,
    get_current_chat_id,
    get_locked_session_count,
    get_session_lock,
    reset_current_chat_id,
    set_current_chat_id,
)

# Pipeline 架构
from .pipeline import (
    BaseProcessor,
    CompressProcessor,
    ContextPipeline,
    ExplicitCacheProcessor,
    FilterProcessor,
    ProcessorContext,
    SessionNotesProcessor,
    SummarizeProcessor,
    ThinkingBlockCleaner,
    build_default_processors,
    create_default_pipeline,
)
from .strategies.compact_rules import COMPACT_RULES
from .strategies.compactor import compress_messages_async, compress_tool_message_async, should_compress
from .strategies.filter import (
    FILTER_TOKEN_THRESHOLD,
    FilteredResult,
    create_filtered_result,
    format_filtered_message,
    should_filter,
)
from .strategies.filters import BaseFilter, FilterContext, FilterResult, SemanticFilter, StructuralFilter
from .strategies.filters.base import SEMANTIC_CONTENT_TYPES, STRUCTURAL_CONTENT_TYPES, detect_content_type
from .strategies.summarizer import generate_structured_summary, should_summarize
from .tracking.artifact_tracker import (
    ArtifactAction,
    ArtifactRecord,
    ArtifactTracker,
    clear_artifact_tracker,
    create_artifact_tracker,
    get_all_active_trackers,
    get_artifact_tracker,
    get_or_create_artifact_tracker,
)
from .tracking.task_metrics import (
    ArchiveRestoreBlockEvent,
    CompressionEvent,
    RefetchEvent,
    TaskMetrics,
    clear_task_metrics,
    create_task_metrics,
    get_all_active_metrics,
    get_or_create_task_metrics,
    get_task_metrics,
    record_archive_refetch_for_path,
)

__all__ = [
    # schemas
    "BUILTIN_PROTECTED_TOOLS",
    "COMPACT_RULES",
    "DEFAULT_BUSINESS_PROTECTED_TOOLS",
    "DEFAULT_CONTEXT_CONFIG",
    "DEFAULT_SOFT_ONLY_TOOLS",
    # filter
    "FILTER_TOKEN_THRESHOLD",
    "SEMANTIC_CONTENT_TYPES",
    "STRUCTURAL_CONTENT_TYPES",
    "TOOL_PROTECTION_CONFIG",
    # context
    "AgentContext",
    "ArchiveRestoreBlockEvent",
    # artifact_tracker
    "ArtifactAction",
    "ArtifactRecord",
    "ArtifactTracker",
    # filters
    "BaseFilter",
    "BaseProcessor",
    "CacheTtlPrunePolicy",
    "CacheUsageFeedback",
    "CompactToolCall",
    "CompressProcessor",
    "CompressionEvent",
    "CompressionIntent",
    "ContextArchiveReference",
    "ContextCompressOffloadCallback",
    "ContextConfig",
    "ContextOffloadResult",
    # pipeline
    "ContextPipeline",
    "ContextSnapshotCallback",
    "ExplicitCacheProcessor",
    "FilterContext",
    "FilterProcessor",
    "FilterResult",
    "FilteredResult",
    "ProcessorContext",
    "RefetchEvent",
    "SemanticFilter",
    "SessionNotesProcessor",
    "StructuralFilter",
    "StructuredSummary",
    "SummarizeProcessor",
    # task_metrics
    "TaskMetrics",
    "ThinkingBlockCleaner",
    "ToolProtectionConfig",
    "ToolPruneMode",
    "acquire_context_lock",
    "build_default_processors",
    "clear_all_locks",
    "clear_artifact_tracker",
    "clear_task_metrics",
    "compress_messages_async",
    "compress_tool_message_async",
    "create_artifact_tracker",
    "create_default_pipeline",
    "create_filtered_result",
    "create_task_metrics",
    "detect_content_type",
    "format_filtered_message",
    "generate_structured_summary",
    "get_active_session_count",
    "get_all_active_metrics",
    "get_all_active_trackers",
    "get_artifact_tracker",
    "get_current_chat_id",
    "get_locked_session_count",
    "get_or_create_artifact_tracker",
    "get_or_create_task_metrics",
    # session_lock
    "get_session_lock",
    "get_task_metrics",
    "record_archive_refetch_for_path",
    "reset_current_chat_id",
    "resolve_cache_ttl_prune_policy",
    "set_current_chat_id",
    # compactor
    "should_compress",
    "should_filter",
    # summarizer
    "should_summarize",
]
