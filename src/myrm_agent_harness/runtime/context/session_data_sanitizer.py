"""Session data sanitization engine for confidential information masking.

Applies configurable rules to redact API keys, private internal IP addresses,
local user home paths, emails, and custom patterns before archiving or export.
"""

import re

from .session_lifecycle_log_archiver_types import (
    ArtifactSnapshotEntry,
    SanitizationPolicy,
    SessionExecutionTurn,
    ToolExecutionLogEntry,
)


class SessionDataSanitizer:
    """Sanitizer engine to scrub sensitive credentials and PII."""

    # API key patterns
    _OPENAI_KEY_RE = re.compile(r"sk-[A-Za-z0-9_\-]{20,}")
    _ANTHROPIC_KEY_RE = re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}")
    _GITHUB_TOKEN_RE = re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")
    _BEARER_AUTH_RE = re.compile(r"(?i)\bbearer\s+([A-Za-z0-9._\-]{20,})")

    # Private IP patterns
    _PRIVATE_IP_10_RE = re.compile(r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
    _PRIVATE_IP_172_RE = re.compile(r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b")
    _PRIVATE_IP_192_RE = re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b")

    # Local filesystem home path patterns
    _MAC_HOME_RE = re.compile(r"/Users/[a-zA-Z0-9_\.\-]+(?=/|$)")
    _LINUX_HOME_RE = re.compile(r"/home/[a-zA-Z0-9_\.\-]+(?=/|$)")
    _WINDOWS_HOME_RE = re.compile(r"[A-Za-z]:\\Users\\[a-zA-Z0-9_\.\-]+(?=\\|$)", re.IGNORECASE)

    # Email pattern
    _EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

    def __init__(self, policy: SanitizationPolicy) -> None:
        """Initialize sanitizer with policy configuration."""
        self._policy = policy
        self._custom_compiled = [re.compile(p) for p in policy.custom_patterns]

    def sanitize_text(self, text: str) -> str:
        """Redact sensitive occurrences in a text string based on active policy."""
        if not text:
            return text

        result = text

        if self._policy.mask_api_keys:
            result = self._OPENAI_KEY_RE.sub("sk-***[REDACTED_API_KEY]***", result)
            result = self._ANTHROPIC_KEY_RE.sub("sk-ant-***[REDACTED_API_KEY]***", result)
            result = self._GITHUB_TOKEN_RE.sub("ghp_***[REDACTED_TOKEN]***", result)
            result = self._BEARER_AUTH_RE.sub("Bearer ***[REDACTED_BEARER]***", result)

        if self._policy.mask_private_ips:
            result = self._PRIVATE_IP_10_RE.sub("10.***[PRIVATE_IP]***", result)
            result = self._PRIVATE_IP_172_RE.sub("172.***[PRIVATE_IP]***", result)
            result = self._PRIVATE_IP_192_RE.sub("192.168.***[PRIVATE_IP]***", result)

        if self._policy.mask_user_home_paths:
            result = self._MAC_HOME_RE.sub("<HOMEDIR>", result)
            result = self._LINUX_HOME_RE.sub("<HOMEDIR>", result)
            result = self._WINDOWS_HOME_RE.sub("<HOMEDIR>", result)

        if self._policy.mask_emails:
            result = self._EMAIL_RE.sub("***@***.***", result)

        for custom_re in self._custom_compiled:
            result = custom_re.sub("***[REDACTED_CUSTOM]***", result)

        return result

    def sanitize_tool_entry(self, entry: ToolExecutionLogEntry) -> ToolExecutionLogEntry:
        """Sanitize argument values, output payloads, and errors of a tool execution log."""
        sanitized_args: dict[str, str] = {
            k: self.sanitize_text(v) for k, v in entry.arguments.items()
        }
        sanitized_result = self.sanitize_text(entry.result_payload)
        sanitized_err = (
            self.sanitize_text(entry.error_message)
            if entry.error_message is not None
            else None
        )

        return ToolExecutionLogEntry(
            call_id=entry.call_id,
            tool_name=entry.tool_name,
            arguments=sanitized_args,
            result_payload=sanitized_result,
            duration_ms=entry.duration_ms,
            status=entry.status,
            timestamp=entry.timestamp,
            error_message=sanitized_err,
        )

    def sanitize_turn(self, turn: SessionExecutionTurn) -> SessionExecutionTurn:
        """Scrub user input, assistant response, and tool logs in an execution turn."""
        clean_user_input = self.sanitize_text(turn.user_input)
        clean_assistant_resp = self.sanitize_text(turn.assistant_response)
        clean_tool_calls = [self.sanitize_tool_entry(tc) for tc in turn.tool_calls]
        clean_errors = [self.sanitize_text(err) for err in turn.errors]

        return SessionExecutionTurn(
            turn_id=turn.turn_id,
            user_input=clean_user_input,
            assistant_response=clean_assistant_resp,
            tool_calls=clean_tool_calls,
            token_billing=turn.token_billing,
            errors=clean_errors,
            timestamp=turn.timestamp,
        )

    def sanitize_artifact(self, artifact: ArtifactSnapshotEntry) -> ArtifactSnapshotEntry:
        """Sanitize artifact textual content and metadata."""
        clean_name = self.sanitize_text(artifact.name)
        clean_content = self.sanitize_text(artifact.content_text)

        return ArtifactSnapshotEntry(
            artifact_id=artifact.artifact_id,
            name=clean_name,
            mime_type=artifact.mime_type,
            content_text=clean_content,
            version_hash=artifact.version_hash,
            created_at=artifact.created_at,
        )

    def sanitize_all(
        self,
        turns: list[SessionExecutionTurn],
        artifacts: list[ArtifactSnapshotEntry],
    ) -> tuple[list[SessionExecutionTurn], list[ArtifactSnapshotEntry]]:
        """Sanitize an entire collection of turns and artifacts."""
        sanitized_turns = [self.sanitize_turn(t) for t in turns]
        sanitized_artifacts = [self.sanitize_artifact(a) for a in artifacts]
        return sanitized_turns, sanitized_artifacts
