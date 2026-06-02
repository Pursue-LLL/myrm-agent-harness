"""Internal helpers for video generation — validation, retryability, truncation.

[OUTPUT]
- is_retryable: Decide whether an exception is retryable based on type name
- safe_truncate: Truncate long error messages with indicator
- validate_video_content: Magic-bytes validation to reject non-video responses

[POS]
Used by generator.py for retry logic, error formatting, and content validation.
"""

from __future__ import annotations

from .models import VideoGenerationError

_ERROR_MSG_MAX_LEN = 500

_NON_RETRYABLE_NAMES = frozenset(
    {
        "AuthenticationError",
        "BadRequestError",
        "NotFoundError",
        "ValueError",
    }
)

_VIDEO_MAGIC_BYTES: tuple[tuple[bytes, int, bytes | None], ...] = (
    (b"ftyp", 4, None),
    (b"\x1a\x45\xdf\xa3", 0, None),
    (b"RIFF", 0, b"AVI "),
)
_MIN_VIDEO_BYTES = 12


def is_retryable(exc: Exception) -> bool:
    """True if the exception type is NOT in the known non-retryable set."""
    return type(exc).__name__ not in _NON_RETRYABLE_NAMES


def safe_truncate(msg: str, max_len: int = _ERROR_MSG_MAX_LEN) -> str:
    """Truncate message to max_len, appending '... [truncated]' if shortened."""
    if len(msg) <= max_len:
        return msg
    return msg[:max_len] + "... [truncated]"


def validate_video_content(
    data: bytes,
    provider_id: str,
    model_id: str,
) -> None:
    """Validate video data via magic bytes to catch non-video responses."""
    if len(data) < _MIN_VIDEO_BYTES:
        raise VideoGenerationError(
            f"Response too small ({len(data)} bytes) from {provider_id}/{model_id}, likely not a valid video"
        )
    for signature, offset, extra_check in _VIDEO_MAGIC_BYTES:
        if data[offset : offset + len(signature)] == signature and (
            extra_check is None or data[8 : 8 + len(extra_check)] == extra_check
        ):
            return
    head_hex = data[:16].hex(" ")
    raise VideoGenerationError(
        f"Invalid video content from {provider_id}/{model_id}: unrecognized format (header: {head_hex})"
    )
