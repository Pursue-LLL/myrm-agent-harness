"""Client-side code secret leak write validator.

[POS]
Validates file write operations (CREATE, APPEND, STR_REPLACE) against browser-facing
code files (.tsx, .jsx, .vue, .html, .js, etc.).
Throws ClientSecretLeakViolationError to physically abort writes that hardcode API keys,
tokens, or database connection strings into frontend components.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.code_execution.security.client_secret_scanner import (
    ClientSideSecretScanner,
    SecretFinding,
)

from ..core.operation_context import OperationType
from .base import Validator

if TYPE_CHECKING:
    from ..core.operation_context import OperationContext

logger = logging.getLogger(__name__)


class ClientSecretLeakViolationError(PermissionError):
    """Raised when hardcoded secrets are detected in client-side/browser code."""

    def __init__(self, findings: list[SecretFinding], file_path: str) -> None:
        self.findings = findings
        self.file_path = file_path

        details = "\n".join(
            f"  - Line {f.line_number}: [{f.secret_type}] {f.matched_snippet} -> Recommend env: {f.suggested_env_var}"
            for f in findings
        )
        msg = (
            f"CRITICAL_SECURITY_LEAK: Detected {len(findings)} hardcoded secret(s) in client-side code '{file_path}'.\n"
            f"Violations:\n{details}\n\n"
            f"FATAL: Secrets in browser-facing code are visible in browser developer tools (F12) "
            f"and public client bundles!\n"
            f"REQUIRED ACTION: Extract credentials to sandbox .env and route requests through a server-side BFF proxy."
        )
        super().__init__(msg)


class ClientSecretWriteValidator(Validator):
    """Intercepts and blocks file write operations containing client-side secret leaks."""

    async def _do_validate(self, context: OperationContext, path: str) -> None:
        """Scan content before write and reject if secrets are present in browser code."""
        # Only validate write mutations
        if context.operation not in (
            OperationType.CREATE,
            OperationType.STR_REPLACE,
        ):
            return

        # Check if the target is client/browser code
        if not ClientSideSecretScanner.is_client_code_file(path):
            return

        contents_to_check: list[str] = []
        if context.operation == OperationType.CREATE and context.file_text:
            contents_to_check.append(context.file_text)
        elif context.operation == OperationType.STR_REPLACE and context.edits:
            for edit in context.edits:
                if edit.new_str:
                    contents_to_check.append(edit.new_str)

        for content in contents_to_check:
            findings = ClientSideSecretScanner.scan_code(content, path)
            if findings:
                logger.error(
                    "Aborted write to client code %s: %d hardcoded secrets detected",
                    path,
                    len(findings),
                )
                raise ClientSecretLeakViolationError(findings, path)
