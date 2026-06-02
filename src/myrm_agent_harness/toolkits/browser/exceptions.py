"""Browser toolkit exception hierarchy.

Provides fine-grained exception types for browser operations with clear
semantic meaning and exception chaining support.

Architecture:
    BrowserError (root)
    ├── BrowserPoolError
    │   ├── BrowserLaunchError
    │   ├── BrowserShutdownError
    │   └── BrowserPoolExhaustedError
    ├── BrowserSessionError
    │   ├── BrowserNavigationError
    │   ├── BrowserTimeoutError
    │   ├── BrowserNetworkError
    │   └── BrowserClosedError
    ├── BrowserToolError
    │   ├── ToolExecutionError
    │   ├── ToolConfigurationError
    │   └── RefNotFoundError
    └── AriaError
        ├── AriaAcquisitionError
        ├── AriaParseError
        └── AriaCrossOriginError

Usage:
    try:
        await pool.acquire_page()
    except BrowserLaunchError as e:
        logger.error(f"Failed to launch browser: {e}")
    except BrowserPoolExhaustedError:
        logger.warning("Browser pool exhausted, waiting...")


[INPUT]
- urllib.parse::urlparse (POS: URL parsing and normalization)

[OUTPUT]
- BrowserError: Root exception for all browser operations
- BrowserPoolError: Pool management errors
- BrowserSessionError: Session operation errors
- BrowserToolError: Tool execution errors
- RefNotFoundError: ref failure exception (structured diagnosis + URL change classification + smart suggestion generation + context refs sampling)
- AriaError: ARIA snapshot errors

[POS]
Exception hierarchy definition. RefNotFoundError provides structured diagnostic info, including URL change classification (path/query/hash/none), smart recovery suggestions, and context refs sampling to help Agents quickly locate issues and recover.
"""

from __future__ import annotations

from typing import Any, Literal
from urllib.parse import urlparse


class BrowserError(Exception):
    """Root exception for all browser toolkit operations (enhanced with diagnostics).

    All browser-related exceptions inherit from this base class, allowing
    broad exception handling when needed while maintaining fine-grained
    exception types for specific error cases.

    Enhanced features:
    - Diagnostic information for root cause analysis
    - Recovery suggestions prioritized by success probability
    - Error classification for metrics and alerting
    """

    def __init__(
        self,
        message: str,
        *,
        context: dict[str, Any] | None = None,
        cause: Exception | None = None,
        diagnostic_info: dict[str, Any] | None = None,
        recovery_suggestions: list[str] | None = None,
        error_code: str | None = None,
    ) -> None:
        """Initialize browser error with message and optional context.

        Args:
            message: Human-readable error description
            context: Optional context data (URL, timeout, etc.)
            cause: Optional underlying exception
            diagnostic_info: Diagnostic information for debugging
            recovery_suggestions: Prioritized list of recovery actions
            error_code: Error classification code
        """
        super().__init__(message)
        self.message = message
        self.context = context or {}
        self.__cause__ = cause
        self.diagnostic_info = diagnostic_info or {}
        self.recovery_suggestions = recovery_suggestions or []
        self.error_code = error_code

    def format_for_llm(self) -> str:
        """Format error for LLM consumption with full diagnostic context."""
        parts = [f"Error: {self.message}"]

        if self.error_code:
            parts.append(f"Error Code: {self.error_code}")

        if self.context:
            parts.append("\nContext:")
            for key, value in self.context.items():
                parts.append(f"  - {key}: {value}")

        if self.diagnostic_info:
            parts.append("\nDiagnostic Info:")
            for key, value in self.diagnostic_info.items():
                parts.append(f"  - {key}: {value}")

        if self.recovery_suggestions:
            parts.append("\nRecovery Suggestions:")
            for i, suggestion in enumerate(self.recovery_suggestions, 1):
                parts.append(f"  {i}. {suggestion}")

        return "\n".join(parts)


class BrowserPoolError(BrowserError):
    """Errors related to browser pool management.

    Raised when browser instance lifecycle operations fail, including
    browser launch, shutdown, and pool resource exhaustion.
    """


class BrowserLaunchError(BrowserPoolError):
    """Failed to launch browser instance.

    Raised when Playwright/Patchright fails to launch a browser process,
    typically due to missing binaries, insufficient resources, or
    conflicting processes.
    """


class BrowserShutdownError(BrowserPoolError):
    """Failed to gracefully shutdown browser instance.

    Raised when browser cleanup operations fail, such as closing contexts
    or terminating browser processes.
    """


class BrowserPoolExhaustedError(BrowserPoolError):
    """Browser pool has no available instances.

    Raised when all browser instances in the pool are currently in use
    and no new instances can be created (pool limit reached).
    """


class BrowserSessionError(BrowserError):
    """Errors related to browser session operations.

    Raised when page-level operations fail, including navigation,
    network errors, timeouts, and closed page issues.
    """


class BrowserNavigationError(BrowserSessionError):
    """Failed to navigate to URL (with intelligent diagnostics).

    Raised when page.goto() or related navigation methods fail,
    typically due to invalid URLs, DNS errors, or server errors.

    Auto-generates recovery suggestions based on error type and status code.
    """

    def __init__(
        self,
        message: str,
        *,
        url: str | None = None,
        status_code: int | None = None,
        error_text: str | None = None,
        context: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        """Initialize navigation error with intelligent diagnostics.

        Args:
            message: Error description
            url: URL that failed to load
            status_code: HTTP status code (if available)
            error_text: Browser error message
            context: Additional context
            cause: Underlying exception
        """
        diagnostic_info = {}
        if url:
            diagnostic_info["url"] = url
        if status_code:
            diagnostic_info["status_code"] = status_code
        if error_text:
            diagnostic_info["error_text"] = error_text

        recovery_suggestions = self._generate_suggestions(url, status_code, error_text)
        error_code = f"BROWSER_NAV_{status_code}" if status_code else "BROWSER_NAV_FAILED"

        super().__init__(
            message,
            context=context,
            cause=cause,
            diagnostic_info=diagnostic_info,
            recovery_suggestions=recovery_suggestions,
            error_code=error_code,
        )

    @staticmethod
    def _generate_suggestions(
        url: str | None,
        status_code: int | None,
        error_text: str | None,
    ) -> list[str]:
        """Generate recovery suggestions based on failure type."""
        suggestions = []

        if status_code:
            if status_code == 404:
                suggestions.extend(
                    [
                        "URL not found - verify the URL is correct",
                        "Check if the page has moved (try searching for the content)",
                        "Try navigating to the site's homepage first",
                    ]
                )
            elif status_code == 403:
                suggestions.extend(
                    [
                        "Access forbidden - the site may require authentication",
                        "Try logging in first if credentials are available",
                        "Check if the site blocks automated browsers (may need stealth mode)",
                    ]
                )
            elif status_code == 500:
                suggestions.extend(
                    [
                        "Server error - the site may be temporarily down",
                        "Wait a few seconds and retry",
                        "Try a different page on the same site to verify server status",
                    ]
                )
            elif status_code >= 400:
                suggestions.append(f"HTTP {status_code} error - check the URL and server status")

        if error_text:
            if "net::ERR_NAME_NOT_RESOLVED" in error_text:
                suggestions.extend(
                    [
                        "DNS resolution failed - check the domain name",
                        "Verify internet connectivity",
                        "Try a well-known site (e.g., google.com) to test connectivity",
                    ]
                )
            elif "net::ERR_CONNECTION_REFUSED" in error_text:
                suggestions.extend(
                    [
                        "Connection refused - the server may be down or unreachable",
                        "Check if the port is correct (HTTP uses 80, HTTPS uses 443)",
                        "Verify the URL scheme (http:// vs https://)",
                    ]
                )
            elif "net::ERR_TIMED_OUT" in error_text:
                suggestions.extend(
                    [
                        "Connection timed out - the server may be slow or unreachable",
                        "Increase navigation timeout and retry",
                        "Check if the site is accessible from your network",
                    ]
                )

        if not suggestions:
            suggestions.extend(
                [
                    "Verify the URL is correct and accessible",
                    "Check browser console for detailed error messages",
                    "Try navigating to a simpler page to isolate the issue",
                ]
            )

        return suggestions


class BrowserTimeoutError(BrowserSessionError):
    """Browser operation timed out (with intelligent diagnostics).

    Raised when operations exceed configured timeout limits, such as
    page load timeouts, element wait timeouts, or network timeouts.

    Auto-generates recovery suggestions based on timeout type and context.
    """

    def __init__(
        self,
        message: str,
        *,
        timeout_seconds: float | None = None,
        operation: str | None = None,
        url: str | None = None,
        context: dict[str, Any] | None = None,
        cause: Exception | None = None,
    ) -> None:
        """Initialize timeout error with intelligent diagnostics.

        Args:
            message: Error description
            timeout_seconds: Timeout limit that was exceeded
            operation: Operation that timed out (navigate, wait, etc.)
            url: URL being accessed when timeout occurred
            context: Additional context
            cause: Underlying exception
        """
        diagnostic_info = {}
        if timeout_seconds:
            diagnostic_info["timeout_seconds"] = timeout_seconds
        if operation:
            diagnostic_info["operation"] = operation
        if url:
            diagnostic_info["url"] = url

        recovery_suggestions = self._generate_suggestions(operation, timeout_seconds)
        error_code = f"BROWSER_TIMEOUT_{operation.upper()}" if operation else "BROWSER_TIMEOUT"

        super().__init__(
            message,
            context=context,
            cause=cause,
            diagnostic_info=diagnostic_info,
            recovery_suggestions=recovery_suggestions,
            error_code=error_code,
        )

    @staticmethod
    def _generate_suggestions(operation: str | None, timeout_seconds: float | None) -> list[str]:
        """Generate recovery suggestions based on operation type."""
        suggestions = []

        if operation == "navigate":
            suggestions.extend(
                [
                    "Increase navigation timeout if the page is known to load slowly",
                    "Check if the URL is accessible (try browser_navigate with a simpler page first)",
                    "Verify network connectivity and DNS resolution",
                    "Check if the page requires authentication or has geo-restrictions",
                ]
            )
        elif operation == "wait":
            suggestions.extend(
                [
                    "The element may not exist on the page - call browser_snapshot to verify",
                    "The element may be dynamically loaded - try waiting longer or use a different selector",
                    "Check if the page structure has changed since last snapshot",
                ]
            )
        elif operation == "load":
            suggestions.extend(
                [
                    "Page has heavy resources or slow backend - increase timeout",
                    "Try navigating to a lighter page first to verify browser connectivity",
                    "Check browser console for JavaScript errors that may block page load",
                ]
            )
        else:
            suggestions.extend(
                [
                    "Increase timeout if the operation is expected to take longer",
                    "Verify the page is in a stable state before retrying",
                    "Check if the operation is blocked by page JavaScript or security policies",
                ]
            )

        if timeout_seconds and timeout_seconds < 10:
            suggestions.append(f"Current timeout ({timeout_seconds}s) is very short - consider increasing to 30s+")

        return suggestions


class BrowserNetworkError(BrowserSessionError):
    """Network-related errors during browser operations.

    Raised when network requests fail due to connection issues,
    DNS resolution failures, or proxy errors.
    """


class BrowserClosedError(BrowserSessionError):
    """Browser page or context has been closed.

    Raised when attempting operations on a closed page or context,
    typically after explicit close() calls or browser crashes.
    """


class BrowserToolError(BrowserError):
    """Errors related to browser tool execution.

    Raised when browser tools (navigation, screenshot, etc.) fail to
    execute, either due to configuration issues or execution failures.
    """


class ToolExecutionError(BrowserToolError):
    """Tool execution failed.

    Raised when a browser tool encounters an error during execution,
    such as element not found, invalid selector, or script errors.
    """


class ToolConfigurationError(BrowserToolError):
    """Tool configuration is invalid.

    Raised when tool parameters are invalid or missing required fields,
    preventing tool execution from starting.
    """


class AriaError(BrowserError):
    """Errors related to ARIA snapshot operations.

    Raised when ARIA tree acquisition, parsing, or rendering fails.
    """


class AriaAcquisitionError(AriaError):
    """Failed to acquire ARIA tree from page/frame.

    Raised when browser fails to generate ARIA tree, typically due to
    invalid selectors, cross-origin restrictions, or script execution errors.
    """


class AriaParseError(AriaError):
    """Failed to parse ARIA YAML.

    Raised when ARIA YAML parsing fails due to malformed YAML, unexpected
    structure, or invalid node definitions.
    """


class AriaCrossOriginError(AriaError):
    """Cross-origin iframe access denied.

    Raised when attempting to access ARIA tree of cross-origin iframe,
    which is blocked by browser security policies.
    """


class RefNotFoundError(BrowserToolError):
    """Element reference not found in current snapshot.

    Provides structured context to help LLM agents diagnose and recover by
    including sample refs and actionable suggestions with URL change detection.

    Attributes:
        ref: The requested ref that was not found
        total_refs: Total count of available refs
        ref_range: Range of ref IDs (first-last)
        context_refs: Sample of available refs grouped by role
        last_snapshot_url: URL when last snapshot was taken (for change detection)
    """

    def __init__(
        self,
        ref: str,
        total_refs: int,
        ref_range: str,
        context_refs: list[dict[str, str]],
        *,
        last_snapshot_url: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        """Initialize RefNotFoundError with structured context and intelligent suggestions.

        Args:
            ref: The requested ref that was not found
            total_refs: Total count of available refs
            ref_range: Range of ref IDs (e.g., "e0-e999")
            context_refs: Sample refs with role/name for LLM diagnosis
            last_snapshot_url: URL when last snapshot was taken (enables smart suggestions)
            context: Additional context (action, text, page_url, etc.)
        """
        self.ref = ref
        self.total_refs = total_refs
        self.ref_range = ref_range
        self.context_refs = context_refs
        self.last_snapshot_url = last_snapshot_url

        context_info = (
            "\n".join(f'  - {r["ref"]}: {r["role"]} "{r["name"]}"' for r in context_refs[:5])
            if context_refs
            else "  (none)"
        )

        current_url = context.get("page_url") if context else None
        suggestion = self._generate_suggestion(current_url, last_snapshot_url)

        message = (
            f"Ref not found: {ref}\n"
            f"Available refs: {self.total_refs} refs ({ref_range})\n"
            f"Context refs:\n{context_info}\n"
            f"{suggestion}"
        )

        super().__init__(message, context=context)

    @staticmethod
    def _classify_url_change(
        last_url: str, current_url: str
    ) -> tuple[Literal["path", "query", "hash", "none"], str, str]:
        """Classify URL change type with normalization.

        Args:
            last_url: Last snapshot URL
            current_url: Current page URL

        Returns:
            (change_type, last_normalized, current_normalized)
            change_type: "path" (navigation) | "query" (params) | "hash" (anchor) | "none" (unchanged)
        """
        if last_url == current_url:
            return ("none", last_url, current_url)

        last = urlparse(last_url)
        curr = urlparse(current_url)

        last_base = f"{last.scheme.lower()}://{last.netloc.lower()}{last.path.rstrip('/') or '/'}"
        curr_base = f"{curr.scheme.lower()}://{curr.netloc.lower()}{curr.path.rstrip('/') or '/'}"

        if last_base != curr_base:
            return ("path", last_base, curr_base)

        if last.query != curr.query:
            last_full = f"{last_base}?{last.query}" if last.query else last_base
            curr_full = f"{curr_base}?{curr.query}" if curr.query else curr_base
            return ("query", last_full, curr_full)

        if last.fragment != curr.fragment:
            return ("hash", last_url, current_url)

        return ("none", last_url, current_url)

    @staticmethod
    def _generate_suggestion(current_url: str | None, last_snapshot_url: str | None) -> str:
        """Generate intelligent suggestion based on URL change detection.

        Args:
            current_url: Current page URL
            last_snapshot_url: URL when last snapshot was taken

        Returns:
            Actionable suggestion message
        """
        if not current_url or not last_snapshot_url:
            return (
                "Suggestion: Page structure may have changed. "
                "Call browser_snapshot(diff=False) to get fresh refs, then retry the interaction."
            )

        change_type, last_norm, curr_norm = RefNotFoundError._classify_url_change(last_snapshot_url, current_url)

        messages = {
            "path": (
                f"Page has navigated from {last_norm} to {curr_norm}. "
                "Call browser_snapshot(diff=False) to get new page refs, then retry the interaction."
            ),
            "query": (
                f"Query params changed ({last_norm} → {curr_norm}). "
                "Call browser_snapshot(diff=False) to refresh dynamic content refs, then retry the interaction."
            ),
            "hash": (
                f"Page scrolled to anchor ({last_norm} → {curr_norm}). "
                "Call browser_snapshot(diff=False) if refs changed, then retry the interaction."
            ),
        }
        return messages.get(
            change_type,
            (
                "Page URL unchanged but ref not found. Possible causes: "
                "dynamic content loaded, element removed, or page structure changed. "
                "Call browser_snapshot(diff=False) to get fresh refs, then retry the interaction."
            ),
        )
