"""HTTP Error Classifier - User-Friendly Error Messages

[INPUT]

[OUTPUT]
- HttpErrorCategory (枚举)
- user_friendly_message (str)

[POS]
HTTP error classifier. Categorizes HTTP exceptions into 6 types and generates user-friendly error messages.

"""

from __future__ import annotations

from enum import Enum

import httpx


class HttpErrorCategory(Enum):
    """HTTP error categories"""

    NETWORK_ERROR = "network_error"
    SERVER_ERROR = "server_error"
    CLIENT_ERROR = "client_error"
    PERMISSION_ERROR = "permission_error"
    RATE_LIMITED = "rate_limited"
    UNKNOWN_ERROR = "unknown_error"


def classify_http_error(error: Exception) -> HttpErrorCategory:
    """Classify HTTP error into categories

    Args:
        error: Exception from HTTP request

    Returns:
        HttpErrorCategory
    """
    if isinstance(error, (httpx.NetworkError, httpx.TimeoutException, httpx.ConnectError, httpx.ReadTimeout)):
        return HttpErrorCategory.NETWORK_ERROR
    elif isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        if status == 429:
            return HttpErrorCategory.RATE_LIMITED
        elif status in (401, 403):
            return HttpErrorCategory.PERMISSION_ERROR
        elif 400 <= status < 500:
            return HttpErrorCategory.CLIENT_ERROR
        elif 500 <= status < 600:
            return HttpErrorCategory.SERVER_ERROR
    return HttpErrorCategory.UNKNOWN_ERROR


def get_user_friendly_message(category: HttpErrorCategory, error: Exception) -> str:
    """Get user-friendly error message

    Args:
        category: HttpErrorCategory
        error: Original exception

    Returns:
        User-friendly message
    """
    messages = {
        HttpErrorCategory.NETWORK_ERROR: "Network connection failed. Please check your internet connection.",
        HttpErrorCategory.PERMISSION_ERROR: "Permission denied. Please check your authentication credentials.",
        HttpErrorCategory.SERVER_ERROR: "Server error. Please try again later.",
        HttpErrorCategory.CLIENT_ERROR: "Client error. Please check your request parameters.",
        HttpErrorCategory.RATE_LIMITED: "Rate limit exceeded. The server is throttling requests. Please wait and retry.",
    }
    prefix = messages.get(category, "Unknown error")
    return f"{prefix} Details: {error}"
