"""Sensitive file validator

Detects and warns about operations on sensitive files (credentials, keys, etc.).

[INPUT]
- agent.config::DEFAULT_FILE_IO_CONFIG, (POS: Configuration and type definitions for the Deep Research system. Pure data structures with no business logic dependencies.)
- agent.security.path_security::SENSITIVE_FILE_PATTERNS (POS: Path security — single source of truth for dangerous paths and sensitive files.)
- core.security.path_pattern::first_matching_pattern (POS: shared path-pattern matcher)

[OUTPUT]
- SensitiveFileValidator: Sensitive file validator

[POS]
Sensitive file validator
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.config import DEFAULT_FILE_IO_CONFIG, FileIOConfig
from myrm_agent_harness.agent.security.path_security import SENSITIVE_FILE_PATTERNS
from myrm_agent_harness.core.security.path_pattern import first_matching_pattern

from ..core.operation_context import OperationType
from .base import Validator

if TYPE_CHECKING:
    from ..core.operation_context import OperationContext

logger = logging.getLogger(__name__)


class SensitiveFileValidator(Validator):
    """Sensitive file validator

    Detects operations on sensitive files and:
    1. Logs security warnings
    2. Blocks read operations on highly sensitive files (optional)
    3. Blocks write operations that could expose secrets
    """

    def __init__(self, io_config: FileIOConfig | None = None, block_sensitive_reads: bool = False) -> None:
        """Initialize validator

        Args:
            io_config: I/O configuration (optional)
            block_sensitive_reads: Whether to block reads of sensitive files (default: False, only warn)
        """
        super().__init__()
        self.io_config = io_config or DEFAULT_FILE_IO_CONFIG
        self.block_sensitive_reads = block_sensitive_reads

    async def _do_validate(self, context: OperationContext, path: str) -> None:
        """Validate sensitive file access"""
        # MCP virtual paths skip validation
        if path.startswith("/mcp/"):
            return

        matched_pattern = first_matching_pattern(path, SENSITIVE_FILE_PATTERNS)
        if matched_pattern is not None:
            self._handle_sensitive_file(context, path, matched_pattern)

    def _handle_sensitive_file(self, context: OperationContext, path: str, matched_pattern: str) -> None:
        """Handle sensitive file access

        Args:
            context: Operation context
            path: File path
            matched_pattern: Matched sensitive file pattern

        Raises:
            PermissionError: If sensitive file access is blocked
        """
        operation = context.operation

        # Log security warning
        if self.io_config.log_sensitive_operations:
            logger.warning(
                f"SECURITY: Sensitive file access detected - "
                f"operation={operation.value}, path={path}, pattern={matched_pattern}"
            )

        # Check if we should block the operation
        if operation == OperationType.VIEW and self.block_sensitive_reads:
            raise PermissionError(
                f"Access to sensitive file is blocked: {path}\n"
                f"Matched pattern: {matched_pattern}\n"
                f"Use another source for this information, or tell the user it is unavailable."
            )

        # Block on write operations (creating/modifying sensitive files)
        if operation in (OperationType.CREATE, OperationType.STR_REPLACE):
            logger.error(
                f"SECURITY WARNING: Attempting to write to sensitive file: {path}\n"
                f"Please ensure no secrets are being exposed."
            )
            raise PermissionError(
                f"Access to sensitive file is blocked: {path}\n"
                f"Matched pattern: {matched_pattern}\n"
                f"Do not route around this restriction. Continue without this file, "
                f"or tell the user which file you could not write."
            )
