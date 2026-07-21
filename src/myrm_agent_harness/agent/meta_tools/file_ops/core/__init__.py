"""Text Editor core business logic module.

提供文件操作的核心服务和抽象。
"""

from .file_operation_service import FileOperationService
from .operation_context import OperationContext, OperationType, ViewRange
from .result_formatter import ResultFormatter
from .file_integrity_guard import FileIntegrityGuard, get_file_integrity_guard

__all__ = [
    "FileOperationService",
    "OperationContext",
    "OperationType",
    "ResultFormatter",
    "FileIntegrityGuard",
    "ViewRange",
    "get_file_integrity_guard",
]
