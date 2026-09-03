"""Operator Error Sanitizer for frontend WebUI/Tauri consumption and internal cause separation.

[INPUT]
- None (Standard library dataclasses, enum, re, traceback, typing)

[OUTPUT]
- SanitizedOperatorError: Formatted, safe, user-facing error contract with internal cause separated
- OperatorErrorSanitizer: Pure-rule sanitizer stripping tracebacks, paths, and internal exceptions

[POS]
Harness-level error transformation layer ensuring zero internal cause leakage, actionable hints, and deterministic error codes for client UIs.
"""

from __future__ import annotations

import re
import traceback
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum


class OperatorErrorCode(StrEnum):
    """Standardized error codes for operator and client UI display."""

    AGENT_BUSY = "AGENT_BUSY"
    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    CONTEXT_OVERFLOW = "CONTEXT_OVERFLOW"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    TIMEOUT = "TIMEOUT"
    AUTHENTICATION_FAILED = "AUTHENTICATION_FAILED"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


@dataclass(frozen=True, slots=True)
class SanitizedOperatorError:
    """Standardized, sanitized operator-facing error payload.

    Attributes:
        ok: Always False for errors.
        code: Machine-readable OperatorErrorCode string.
        message: Clean, human-readable summary without internal tracebacks or secrets.
        hint: Actionable remediation suggestion for the user/operator.
        category: Broad category of the fault (e.g. 'TOOL', 'ENV', 'CONFIG', 'SYSTEM').
        details: Optional sanitized context properties (safe key-value pairs).
        internal_cause: Retained internally for server-side logging/diagnostics, NOT for UI display.
    """

    code: OperatorErrorCode
    message: str
    hint: str
    ok: bool = False
    category: str = "SYSTEM"
    details: Mapping[str, str] = field(default_factory=dict)
    internal_cause: str | None = None

    def to_client_dict(self) -> dict[str, object]:
        """Serialize safe payload for WebUI/Tauri clients without internal_cause."""
        return {
            "ok": False,
            "code": str(self.code),
            "message": self.message,
            "hint": self.hint,
            "category": self.category,
            "details": dict(self.details),
        }


class OperatorErrorSanitizer:
    """Pure-rule error sanitizer converting raw Python exceptions to safe operator errors."""

    # Regex patterns for stripping sensitive absolute paths and tracebacks
    _PATH_PATTERN = re.compile(r"(/[a-zA-Z0-9_\-\.]+)+/[a-zA-Z0-9_\-\.]+\.(?:py|sh|ts|js|json|yaml|yml)")
    _TRACEBACK_PATTERN = re.compile(r"Traceback \(most recent call last\):.*?(?=[A-Z][a-zA-Z]+Error:|\Z)", re.DOTALL)

    @classmethod
    def sanitize(
        cls,
        error: BaseException | str,
        *,
        fallback_code: OperatorErrorCode = OperatorErrorCode.INTERNAL_ERROR,
        custom_hint: str | None = None,
    ) -> SanitizedOperatorError:
        """Sanitize an arbitrary exception or error string into a structured operator error."""
        raw_msg = str(error) if isinstance(error, BaseException) else str(error)
        internal_cause = traceback.format_exc() if isinstance(error, BaseException) else raw_msg

        # Extract exception class name if available
        exc_name = type(error).__name__ if isinstance(error, BaseException) else "Error"
        msg_lower = raw_msg.lower()

        # 1. Deterministic classification by error types and signatures
        code = fallback_code
        category = "SYSTEM"
        hint = custom_hint or "Please retry or review agent configuration."

        if "busy" in msg_lower or exc_name == "AgentBusyError":
            code = OperatorErrorCode.AGENT_BUSY
            category = "AGENT"
            hint = "Agent is processing another request. Please wait for the current turn to complete."
        elif "permission" in msg_lower or "forbidden" in msg_lower or "access denied" in msg_lower:
            code = OperatorErrorCode.PERMISSION_DENIED
            category = "SECURITY"
            hint = "Check file or API access permissions in the sandbox environment."
        elif "timeout" in msg_lower or "timed out" in msg_lower or "timeouterror" in msg_lower:
            code = OperatorErrorCode.TIMEOUT
            category = "TIMEOUT"
            hint = "The operation timed out. Consider increasing timeout threshold or simplifying the task."
        elif "not found" in msg_lower or "filenotfounderror" in msg_lower or "404" in msg_lower:
            code = OperatorErrorCode.RESOURCE_NOT_FOUND
            category = "RESOURCE"
            hint = "Verify that the requested file, URL, or resource exists."
        elif "unauthorized" in msg_lower or "auth" in msg_lower or "invalid api key" in msg_lower:
            code = OperatorErrorCode.AUTHENTICATION_FAILED
            category = "AUTH"
            hint = "Check your API keys or credentials in settings."
        elif "token" in msg_lower and ("overflow" in msg_lower or "exceeded" in msg_lower or "limit" in msg_lower):
            code = OperatorErrorCode.CONTEXT_OVERFLOW
            category = "MODEL"
            hint = "Context limit reached. Reset or compact conversation history."
        elif "toolexecutionerror" in exc_name.lower() or "tool" in msg_lower:
            code = OperatorErrorCode.TOOL_EXECUTION_FAILED
            category = "TOOL"
            hint = "The tool encountered an error during execution. Review tool arguments."

        # 2. Clean message: remove tracebacks, memory pointers, and absolute paths
        cleaned_message = cls._TRACEBACK_PATTERN.sub("", raw_msg).strip()
        cleaned_message = cls._PATH_PATTERN.sub("<redacted_path>", cleaned_message)
        # Remove object repr pointers like <Foo object at 0x7f8b90>
        cleaned_message = re.sub(r"<[a-zA-Z0-9_\.]+ object at 0x[0-9a-fA-F]+>", "<object>", cleaned_message)

        if not cleaned_message:
            cleaned_message = f"An internal {exc_name} occurred."

        return SanitizedOperatorError(
            code=code,
            message=cleaned_message,
            hint=hint,
            ok=False,
            category=category,
            internal_cause=internal_cause,
        )
