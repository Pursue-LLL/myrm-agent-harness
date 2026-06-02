"""Web Search exceptions with structured error info and format_for_llm protocol.

[INPUT]
- (none)

[OUTPUT]
- WebSearchError: base exception (implements format_for_llm protocol)
- ErrorContext: structured error context dataclass
- SearchAPIError: API failure with ErrorContext (retryable, status_code)
- SearchConfigError: configuration error (missing API key)
- AllQueriesFailedError: all queries failed with failure details

[POS]
Web Search exception hierarchy. All exceptions implement format_for_llm() so
tool_interceptor_middleware can pass structured diagnostics to the LLM.
"""

import time
from dataclasses import dataclass, field


@dataclass
class ErrorContext:
    """Structured error context for search failures."""

    query: str | None = None
    status_code: int | None = None
    error_code: str | None = None
    response_body: str | None = None
    timestamp: float = field(default_factory=time.time)
    retryable: bool = False
    metadata: dict[str, str] = field(default_factory=dict)


class WebSearchError(Exception):
    """Web Search base exception with format_for_llm protocol."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)

    def format_for_llm(self) -> str:
        return f"Error: {self.message}"


class SearchAPIError(WebSearchError):
    """Search API unavailable or returned error (with ErrorContext diagnostics)."""

    def __init__(self, message: str, context: ErrorContext | None = None):
        super().__init__(message)
        self.context = context or ErrorContext()

    def __str__(self) -> str:
        parts = [self.message]
        if self.context.query:
            parts.append(f"query={self.context.query}")
        if self.context.status_code:
            parts.append(f"status={self.context.status_code}")
        if self.context.error_code:
            parts.append(f"code={self.context.error_code}")
        return " | ".join(parts)

    def format_for_llm(self) -> str:
        ctx = self.context
        parts = [f"Error: {self.message}"]

        if ctx.error_code:
            parts.append(f"Error Code: {ctx.error_code}")
        if ctx.status_code:
            parts.append(f"HTTP Status: {ctx.status_code}")
        if ctx.retryable:
            parts.append("\nHint: This error is retryable. Wait a moment and try again.")
        else:
            parts.append(
                "\nHint: This error is not retryable. Check the search configuration or try a different query."
            )
        if ctx.query:
            parts.append(f"\nDiagnostic Info:\n  - query: {ctx.query}")
        if ctx.response_body:
            snippet = ctx.response_body[:200]
            parts.append(f"  - response_snippet: {snippet}")

        return "\n".join(parts)


class SearchConfigError(WebSearchError):
    """Search configuration error (e.g. missing API key)."""

    def __init__(self, message: str, config_key: str | None = None):
        super().__init__(message)
        self.config_key = config_key

    def __str__(self) -> str:
        if self.config_key:
            return f"{self.message} (config_key={self.config_key})"
        return self.message

    def format_for_llm(self) -> str:
        parts = [f"Error: {self.message}"]
        if self.config_key:
            parts.append(f"\nDiagnostic Info:\n  - config_key: {self.config_key}")
        parts.append(
            "\nHint: This is a server configuration issue. The search service cannot be used until it is resolved."
        )
        return "\n".join(parts)


class AllQueriesFailedError(WebSearchError):
    """All queries failed (with failure details)."""

    def __init__(
        self,
        message: str,
        failed_queries: list[tuple[str, str]] | None = None,
        primary_context: ErrorContext | None = None,
    ):
        super().__init__(message)
        self.failed_queries = failed_queries or []
        self.primary_context = primary_context
        self.timestamp = time.time()

    def __str__(self) -> str:
        if self.failed_queries:
            failed_info = ", ".join([f"{q[:20]}..." for q, _ in self.failed_queries[:3]])
            return f"{self.message} | failed: {failed_info} (total: {len(self.failed_queries)})"
        return self.message

    def format_for_llm(self) -> str:
        parts = [f"Error: {self.message}"]

        ctx = self.primary_context
        if ctx:
            if ctx.error_code:
                parts.append(f"Error Code: {ctx.error_code}")
            if ctx.retryable:
                parts.append(
                    "\nHint: This error is retryable. Wait a moment and try again with the same or simplified queries."
                )
            else:
                parts.append(
                    "\nHint: This error is not retryable. Try different search queries or check if the search service is available."
                )
        else:
            parts.append("\nHint: Try different or simpler search queries.")

        if self.failed_queries:
            parts.append(f"\nFailed queries ({len(self.failed_queries)}):")
            for query, reason in self.failed_queries[:5]:
                parts.append(f'  - "{query[:50]}": {reason[:100]}')

        return "\n".join(parts)
