"""Text Editor core business logic module.

[INPUT]
- file_ops/observers, validators, strategies: file operation sub-domains
- toolkits (storage, shared exceptions) / utils (crypto, db, coercion)
- file_parsers.pdf.pdf::PDFPlumberParser (POS: PDF parser based on pdfplumber.
  Implements text layout preservation, Markdown table extraction, and PDF bookmark
  injection)
- file_parsers.pdf.pdf_content_extractor::extract_pdf_content (POS: Smart PDF
  extraction orchestrator — Text / Hybrid / Image strategy + OCR fallback)

[OUTPUT]
- FileOperationService: file operation service (vault markdown FM preserve +
  Office text-write warnings, archive context read guards)
- FileIntegrityGuard / get_file_integrity_guard: read-before-write + content-hash
  version gates, per-agent tracking
- OperationContext / OperationType / StrReplaceEdit / ViewRange: edit context
- ResultFormatter: FileContent / DirectoryListing / ResultFormatter result types
- normalize_edits_payload / merge_edits_for_diff: file_edit payload normalizer
- build_multimodal_result / append_media_text_parts / process_text_paths:
  file_read execution handlers
- truncate_file_output: file_read output truncation
- append_mcp_docs_next_step_hint / is_mcp_function_doc_batch: MCP batch-read hint

[POS]
file_ops 核心业务逻辑子包。聚合工具执行时的核心服务、编辑上下文、读取处理
与校验抽象，供 file_edit_tool / file_read_tool / file_write_tool 门面消费。
"""

from .file_edit_normalizer import merge_edits_for_diff, normalize_edits_payload
from .file_integrity_guard import FileIntegrityGuard, get_file_integrity_guard
from .file_operation_service import FileOperationService
from .file_read_handlers import (
    append_media_text_parts,
    build_multimodal_result,
    process_text_paths,
)
from .file_read_truncation import truncate_file_output
from .mcp_read_next_step_hint import (
    append_mcp_docs_next_step_hint,
    is_mcp_function_doc_batch,
)
from .operation_context import (
    OperationContext,
    OperationType,
    StrReplaceEdit,
    ViewRange,
)
from .result_formatter import ResultFormatter

__all__ = [
    "FileIntegrityGuard",
    "FileOperationService",
    "OperationContext",
    "OperationType",
    "ResultFormatter",
    "StrReplaceEdit",
    "ViewRange",
    "append_mcp_docs_next_step_hint",
    "append_media_text_parts",
    "build_multimodal_result",
    "get_file_integrity_guard",
    "is_mcp_function_doc_batch",
    "merge_edits_for_diff",
    "normalize_edits_payload",
    "process_text_paths",
    "truncate_file_output",
]
