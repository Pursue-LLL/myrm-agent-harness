"""Sensitive file validator

Detects and warns about operations on sensitive files (credentials, keys, etc.).

[INPUT]
- agent.config::DEFAULT_FILE_IO_CONFIG, (POS: Configuration and type definitions for the Deep Research system. Pure data structures with no business logic dependencies.)
- agent.security.path_security::SENSITIVE_FILE_PATTERNS (POS: Path security — single source of truth for dangerous paths and sensitive files.)

[OUTPUT]
- SensitiveFileValidator: Sensitive file validator

[POS]
Sensitive file validator
"""

from __future__ import annotations

import logging
from fnmatch import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.agent.config import DEFAULT_FILE_IO_CONFIG, FileIOConfig
from myrm_agent_harness.agent.security.path_security import SENSITIVE_FILE_PATTERNS

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

        # Get file name and path for pattern matching
        path_obj = Path(path)
        file_name = path_obj.name
        abs_path = str(path_obj.absolute())

        # Check against sensitive file patterns
        for pattern in SENSITIVE_FILE_PATTERNS:
            if self._matches_pattern(abs_path, file_name, pattern):
                self._handle_sensitive_file(context, path, pattern)
                break

    def _matches_pattern(self, abs_path: str, file_name: str, pattern: str) -> bool:
        """Check if file matches sensitive pattern

        Args:
            abs_path: Absolute file path
            file_name: File name
            pattern: Glob pattern to match

        Returns:
            True if file matches pattern
        """
        # Match against full path with glob pattern
        if fnmatch(abs_path, pattern):
            return True

        # Match against file name only (remove directory wildcards)
        file_pattern = pattern.replace("**/", "")
        if fnmatch(file_name, file_pattern):
            return True

        # Special handling for exact file name patterns (without wildcards)
        # This handles cases like ".env" without matching "environment.txt"
        pattern_cleaned = pattern.replace("**/", "").replace("**", "")

        # Only do substring match if pattern doesn't contain wildcards
        # and is a complete filename or extension
        if "*" not in pattern_cleaned:
            # Check if it's an exact filename match
            if file_name == pattern_cleaned:
                return True

            # Check if it's in the path as a complete path component
            # Use path separators to ensure we match complete components
            path_components = abs_path.replace("\\", "/").split("/")
            if pattern_cleaned in path_components:
                return True

            # Check for dotfile patterns (e.g., ".env" matches ".env.local")
            # Ensure dotfile match is either exact or followed by a dot
            if (
                pattern_cleaned.startswith(".")
                and file_name.startswith(pattern_cleaned)
                and (len(file_name) == len(pattern_cleaned) or file_name[len(pattern_cleaned)] == ".")
            ):
                return True

        return False

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
                f"This file may contain credentials or secrets."
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
                f"Writing to sensitive files is strictly prohibited by security policies."
            )
