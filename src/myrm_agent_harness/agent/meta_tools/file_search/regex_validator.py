"""Regex safety validator

Validates regex patterns to prevent ReDoS (Regular Expression Denial of Service) attacks.

[INPUT]
- utils.errors::ToolError (POS: Storage quota related errors.)
- agent.config::FileIOConfig (POS: Configuration and type definitions for the Deep Research system. Pure data structures with no business logic dependencies.)

[OUTPUT]
- RegexTimeoutError: Timeout exception for regex operations
- RegexValidator: Regex safety validator
- time_limit: Context manager to limit execution time (cross-platform)

[POS]
Regex safety validator
"""

from __future__ import annotations

import logging
import platform
import re
import signal
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import TYPE_CHECKING, TypeVar

from myrm_agent_harness.utils.errors import ToolError

if TYPE_CHECKING:
    from myrm_agent_harness.agent.config import FileIOConfig

T = TypeVar("T")

logger = logging.getLogger(__name__)


class RegexTimeoutError(Exception):
    """Timeout exception for regex operations"""

    pass


def _timeout_wrapper[T](func: Callable[[], T], timeout: float) -> T:
    """Wrapper to run function with timeout using threading (cross-platform)

    Args:
        func: Function to execute
        timeout: Timeout in seconds

    Returns:
        Function result

    Raises:
        RegexTimeoutError: If function execution exceeds timeout
    """
    result: list[T] = []
    exception: list[Exception] = []

    def target() -> None:
        try:
            result.append(func())
        except Exception as e:
            exception.append(e)

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)

    if thread.is_alive():
        # Thread is still running, timeout occurred
        # Note: We can't forcefully kill the thread, but we can return timeout error
        raise RegexTimeoutError(f"Operation timed out after {timeout}s")

    if exception:
        raise exception[0]

    if result:
        return result[0]

    raise RegexTimeoutError("Operation completed without result")


@contextmanager
def time_limit(seconds: float) -> Generator[None]:
    """Context manager to limit execution time (cross-platform)

    Args:
        seconds: Maximum execution time in seconds

    Raises:
        RegexTimeoutError: If execution exceeds time limit

    Note:
        Uses signal-based timeout on Unix-like systems and threading on Windows
    """
    is_windows = platform.system() == "Windows"

    if not is_windows:
        # Unix-like systems: use signal-based timeout
        def signal_handler(signum: int, frame: object) -> None:
            raise RegexTimeoutError("Operation timed out")

        try:
            signal.signal(signal.SIGALRM, signal_handler)
            signal.setitimer(signal.ITIMER_REAL, seconds)
            try:
                yield
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0)
            return
        except (AttributeError, ValueError):
            # Signal not available, fall through to threading approach
            pass

    # Windows or signal not available: yield without timeout protection
    # Note: For Windows, timeout is handled at the call site using _timeout_wrapper
    logger.debug("Using threading-based timeout mechanism")
    yield


class RegexValidator:
    """Regex safety validator

    Validates regex patterns to prevent:
    1. Catastrophic backtracking (ReDoS)
    2. Overly complex patterns
    3. Extremely long patterns
    """

    def __init__(self, io_config: FileIOConfig) -> None:
        """Initialize validator

        Args:
            io_config: I/O configuration with regex safety settings
        """
        self.io_config = io_config

    def validate_and_compile(self, pattern: str, flags: int = 0) -> re.Pattern[str]:
        """Validate and compile regex pattern safely

        Args:
            pattern: Regex pattern to validate
            flags: Regex flags (e.g., re.IGNORECASE)

        Returns:
            Compiled regex pattern

        Raises:
            ToolError: If pattern is unsafe or invalid
        """
        # Check pattern length
        if len(pattern) > self.io_config.max_regex_length:
            raise ToolError(
                message=f"Regex pattern too long: {len(pattern)} chars (max: {self.io_config.max_regex_length})",
                user_hint=f"The regex pattern is too long. Please use a simpler pattern (max {self.io_config.max_regex_length} characters).",
            )

        # Check for dangerous patterns
        self._check_dangerous_patterns(pattern)

        # Compile with timeout
        is_windows = platform.system() == "Windows"

        try:
            if is_windows:
                # Windows: use threading-based timeout
                def compile_func() -> re.Pattern[str]:
                    return re.compile(pattern, flags)

                compiled = _timeout_wrapper(compile_func, self.io_config.regex_timeout_seconds)
            else:
                # Unix-like: use signal-based timeout
                with time_limit(self.io_config.regex_timeout_seconds):
                    compiled = re.compile(pattern, flags)

            return compiled
        except RegexTimeoutError as e:
            raise ToolError(
                message=f"Regex compilation timed out: {pattern}",
                user_hint="The regex pattern is too complex and took too long to compile. Please use a simpler pattern.",
            ) from e
        except re.error as e:
            raise ToolError(
                message=f"Invalid regex pattern: {pattern} - {e}",
                user_hint=f"The regex pattern is invalid: {e}. Please check the syntax and try again.",
            ) from e

    def _check_dangerous_patterns(self, pattern: str) -> None:
        """Check for known dangerous regex patterns

        Args:
            pattern: Regex pattern to check

        Raises:
            ToolError: If pattern matches dangerous patterns
        """
        # Check for exact dangerous pattern structures
        # These are known to cause catastrophic backtracking
        dangerous_structures = [
            (r"\(.+\)\+", "(.+)+"),  # Nested repetition of .+
            (r"\(.*\)\*", "(.*)* "),  # Nested repetition of .*
            (r"\(.+\)\*", "(.+)*"),  # Mixed nested repetition
            (r"\(.*\)\+", "(.*)+"),  # Mixed nested repetition
        ]

        for pattern_regex, description in dangerous_structures:
            try:
                if re.search(pattern_regex, pattern):
                    raise ToolError(
                        message=f"Dangerous regex pattern detected: {pattern}",
                        user_hint=(
                            f"The regex pattern contains a dangerous construct ({description}) that could cause "
                            "severe performance issues (ReDoS). This pattern can lead to catastrophic backtracking. "
                            "Please rewrite the pattern without nested quantifiers."
                        ),
                    )
            except re.error:
                # If pattern_regex itself is invalid, skip it
                continue

        # Additional heuristic checks
        self._check_nested_quantifiers(pattern)
        self._check_alternation_complexity(pattern)

    def _check_nested_quantifiers(self, pattern: str) -> None:
        """Check for nested quantifiers (common ReDoS cause)

        Args:
            pattern: Regex pattern to check

        Raises:
            ToolError: If nested quantifiers detected
        """
        # Pattern to detect nested quantifiers: (X+)+ or (X*)* or (X+)*
        nested_quantifier_pattern = r"\([^)]*[*+]\)[*+]"
        if re.search(nested_quantifier_pattern, pattern):
            raise ToolError(
                message=f"Nested quantifiers detected in pattern: {pattern}",
                user_hint=(
                    "The regex pattern contains nested quantifiers (e.g., (X+)+) which can cause "
                    "severe performance issues. Please rewrite the pattern without nested repetition."
                ),
            )

    def _check_alternation_complexity(self, pattern: str) -> None:
        """Check for overly complex alternations

        Args:
            pattern: Regex pattern to check

        Raises:
            ToolError: If pattern has too many alternations
        """
        # Count number of alternations (|)
        alternation_count = pattern.count("|")
        if alternation_count > 20:
            raise ToolError(
                message=f"Too many alternations in pattern: {alternation_count}",
                user_hint=(
                    f"The regex pattern has {alternation_count} alternations (|), which is excessive. "
                    "Please simplify the pattern or split it into multiple searches."
                ),
            )

    def safe_search(
        self, compiled_pattern: re.Pattern[str], text: str, timeout: float | None = None
    ) -> re.Match[str] | None:
        """Perform safe regex search with timeout

        Args:
            compiled_pattern: Compiled regex pattern
            text: Text to search
            timeout: Custom timeout in seconds (optional)

        Returns:
            Match object or None

        Raises:
            ToolError: If search times out
        """
        timeout_seconds = timeout or self.io_config.regex_timeout_seconds
        is_windows = platform.system() == "Windows"

        try:
            if is_windows:
                # Windows: use threading-based timeout
                def search_func() -> re.Match[str] | None:
                    return compiled_pattern.search(text)

                return _timeout_wrapper(search_func, timeout_seconds)
            else:
                # Unix-like: use signal-based timeout
                with time_limit(timeout_seconds):
                    return compiled_pattern.search(text)
        except RegexTimeoutError as e:
            raise ToolError(
                message=f"Regex search timed out after {timeout_seconds}s",
                user_hint="The regex search took too long. The pattern may be causing performance issues. Please use a simpler pattern.",
            ) from e
