"""Artifacts system — artifact lifecycle management.

职责划分：
- 框架层：追踪生成的文件（ArtifactRegistry）、提供类型定义（ArtifactInfo）、安全工具函数
- 业务层：持久化文件、生成 URL、元数据管理
"""

# Constants & Security
from .constants import (
    ACTIVE_CONTENT_MIME_TYPES,
    EXTENSION_TO_ARTIFACT_TYPE,
    EXTENSION_TO_LANGUAGE,
    ArtifactMappings,
    ArtifactType,
    get_all_mappings,
    infer_artifact_type_from_extension,
    infer_artifact_type_from_mime,
    infer_language_from_extension,
    is_active_content,
    is_text_content,
)

# Context
from .context import ArtifactContext, ArtifactContextManager, get_artifact_context

# File ID Registry
from .file_id_registry import (
    FILE_ID_PATTERN,
    FILE_ID_PREFIX,
    FileIdRegistry,
    is_file_id,
    register_file,
    resolve_file_id,
    resolve_file_ids_in_text,
)

# Filters
from .filters import should_filter_skill_resource, should_ignore_artifact

# Registry
from .registry import (
    ArtifactRegistry,
    GeneratedFile,
    InlineArtifactEvent,
    InlineArtifactQueue,
    RealtimeContentEvent,
    RealtimeContentQueue,
    get_artifact_registry,
    get_inline_artifact_queue,
    get_realtime_content_queue,
    push_inline_artifact,
    push_realtime_content,
    register_generated_files,
)

# Types
from .types import ArtifactInfo, infer_artifact_type, infer_language

# UI Artifacts
from .ui_artifact import UIArtifact, UIDataUpdate

# UI Registry
from .ui_registry import UIRegistry, get_ui_registry, pop_pending_ui_events_for_message, register_ui_artifact

__all__ = [
    "ACTIVE_CONTENT_MIME_TYPES",
    "EXTENSION_TO_ARTIFACT_TYPE",
    "EXTENSION_TO_LANGUAGE",
    "FILE_ID_PATTERN",
    "FILE_ID_PREFIX",
    # Context
    "ArtifactContext",
    "ArtifactContextManager",
    "ArtifactInfo",
    "ArtifactMappings",
    "ArtifactRegistry",
    # Constants & Security
    "ArtifactType",
    # File ID Registry
    "FileIdRegistry",
    # Registry
    "GeneratedFile",
    "InlineArtifactEvent",
    "InlineArtifactQueue",
    "RealtimeContentEvent",
    "RealtimeContentQueue",
    # UI Artifacts
    "UIArtifact",
    "UIDataUpdate",
    # UI Registry
    "UIRegistry",
    "get_all_mappings",
    "get_artifact_context",
    "get_artifact_registry",
    "get_inline_artifact_queue",
    "get_realtime_content_queue",
    "get_ui_registry",
    "register_ui_artifact",
    "pop_pending_ui_events_for_message",
    # Types
    "infer_artifact_type",
    "infer_artifact_type_from_extension",
    "infer_artifact_type_from_mime",
    "infer_language",
    "infer_language_from_extension",
    "is_active_content",
    "is_file_id",
    "is_text_content",
    "push_inline_artifact",
    "push_realtime_content",
    "register_file",
    "register_generated_files",
    "resolve_file_id",
    "resolve_file_ids_in_text",
    # Filters
    "should_filter_skill_resource",
    "should_ignore_artifact",
]
