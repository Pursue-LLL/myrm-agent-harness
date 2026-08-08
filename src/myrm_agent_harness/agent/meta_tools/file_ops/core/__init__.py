"""Text Editor core business logic module.

提供文件操作的核心服务和抽象。
"""

from .file_integrity_guard import FileIntegrityGuard, get_file_integrity_guard
from .file_operation_service import FileOperationService
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
    "get_file_integrity_guard",
]
