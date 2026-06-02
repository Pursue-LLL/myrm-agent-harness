"""Binary file validator

Detects and blocks writing binary data or garbled text to files.

[INPUT]
- agent.meta_tools.file_ops.core.operation_context::OperationContext, OperationType (POS: 操作上下文和类型)

[OUTPUT]
- BinaryValidator: Binary file validator

[POS]
Binary file validator
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..core.operation_context import OperationType
from .base import Validator

if TYPE_CHECKING:
    from ..core.operation_context import OperationContext

logger = logging.getLogger(__name__)


class BinaryValidator(Validator):
    """Binary file validator

    Detects operations that attempt to write binary data or garbled text
    to files, and blocks them to prevent file corruption.
    """

    def __init__(self) -> None:
        """Initialize validator"""
        super().__init__()

    async def _do_validate(self, context: OperationContext, path: str) -> None:
        """Validate file content for binary data"""
        # Only check write operations
        if context.operation not in (OperationType.CREATE, OperationType.STR_REPLACE):
            return

        content_to_check = ""
        if context.operation == OperationType.CREATE and context.file_text:
            content_to_check = context.file_text
        elif context.operation == OperationType.STR_REPLACE and context.new_str:
            content_to_check = context.new_str

        if not content_to_check:
            return

        self._check_binary_content(path, content_to_check)

    def _check_binary_content(self, path: str, content: str) -> None:
        """Check if content appears to be binary.

        Uses a robust heuristic similar to Git: checks for null bytes in the content.
        Avoids ratio-based checks to prevent false positives with ANSI escape codes
        or rich Unicode text.

        Args:
            path: File path
            content: Content to check

        Raises:
            ValueError: If content appears to be binary
        """
        # Check for null bytes which strongly indicate binary data
        # We only check the first 8000 characters for performance, similar to Git's heuristic
        chunk_to_check = content[:8000]
        if "\x00" in chunk_to_check:
            logger.error(f"SECURITY: Attempted to write null bytes to {path}")
            raise ValueError(
                f"Validation failed: Attempted to write binary data (null bytes) to {path}. "
                f"The file_write and file_edit tools only support writing text files."
            )
