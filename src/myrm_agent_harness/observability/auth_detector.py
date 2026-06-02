"""Authentication failure detector for circuit breaker

Detect authentication failures to distinguish them from transient errors.
Auth failures should trigger immediate circuit breaking instead of retries.

[INPUT]
- Exception (POS: Any exception from LLM calls)

[OUTPUT]
- detect_auth_failure: Determine if exception is auth-related

[POS]
Authentication failure detection for circuit breaker logic.
Used to distinguish permanent failures (auth errors) from transient failures (network timeouts).
Auth failures should not trigger retries, but should immediately open the circuit breaker.

Design rationale:
- Auth failures are permanent: retrying won't help
- Network failures are transient: retries may succeed
- Provider-specific error patterns: OpenAI, Anthropic, etc.
"""

import re

# Auth failure patterns across multiple LLM providers
_AUTH_ERROR_PATTERNS = [
    # Generic patterns
    r"401",
    r"403",
    r"unauthorized",
    r"authentication.*error",
    r"authentication.*failed",
    r"invalid.*credentials",
    # OpenAI specific
    r"invalid_api_key",
    r"incorrect_api_key",
    r"api.*key.*expired",
    r"api.*key.*invalid",
    # Anthropic specific
    r"authentication_error",
    r"invalid_x_api_key",
    # Google/Gemini specific
    r"unauthenticated",
    r"invalid.*api.*token",
    # Generic quota/permission (treat as auth-related)
    r"permission.*denied",
    r"access.*denied",
]

_AUTH_REGEX = re.compile("|".join(f"({p})" for p in _AUTH_ERROR_PATTERNS), re.IGNORECASE)


def detect_auth_failure(exception: Exception) -> bool:
    """Detect if exception is an authentication failure

    Auth failures are permanent errors that won't be resolved by retries.
    Circuit breaker should immediately open on auth failures.

    Args:
        exception: Exception from LLM call

    Returns:
        True if exception is auth-related, False otherwise

    Examples:
        >>> detect_auth_failure(Exception("OpenAI API error: invalid_api_key"))
        True
        >>> detect_auth_failure(Exception("Connection timeout"))
        False
    """
    error_str = str(exception)
    return bool(_AUTH_REGEX.search(error_str))


def get_auth_error_hint(exception: Exception) -> str:
    """Get user-friendly hint for auth failure

    Args:
        exception: Auth-related exception

    Returns:
        User-friendly error message with actionable hints
    """
    error_str = str(exception).lower()

    if "openai" in error_str or "invalid_api_key" in error_str:
        return (
            "OpenAI API key is invalid or expired. Please check your OPENAI_API_KEY environment variable or .env file."
        )

    if "anthropic" in error_str or "authentication_error" in error_str:
        return "Anthropic API key is invalid or expired. Please check your ANTHROPIC_API_KEY environment variable or .env file."

    if "google" in error_str or "gemini" in error_str:
        return "Google/Gemini API key is invalid. Please check your GOOGLE_API_KEY environment variable or .env file."

    return "LLM API authentication failed. Please verify your API keys in environment variables or .env file."
