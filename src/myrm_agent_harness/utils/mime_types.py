"""Centralized image MIME type utilities.

Provides extension ↔ MIME mappings and magic-bytes detection used by
image generation, video generation, and channel media modules.
"""

from __future__ import annotations

IMAGE_MIME_TYPES: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}

IMAGE_EXTENSIONS: frozenset[str] = frozenset(IMAGE_MIME_TYPES)

_MIME_TO_EXTENSION: dict[str, str] = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/bmp": "bmp",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/ogg": "ogg",
    "audio/flac": "flac",
    "audio/mp4": "m4a",
    "audio/aac": "aac",
    "video/mp4": "mp4",
    "video/webm": "webm",
    "video/ogg": "ogv",
}

_MAGIC_SIGNATURES: tuple[tuple[bytes, int, bytes | None, str], ...] = (
    (b"\xff\xd8\xff", 0, None, "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", 0, None, "image/png"),
    (b"RIFF", 0, b"WEBP", "image/webp"),
    (b"GIF87a", 0, None, "image/gif"),
    (b"GIF89a", 0, None, "image/gif"),
    (b"BM", 0, None, "image/bmp"),
)


def detect_image_mime(data: bytes, fallback: str = "image/png") -> str:
    """Detect image MIME type from leading magic bytes.

    Checks JPEG, PNG, WebP, and GIF signatures.  Returns *fallback*
    when the data is too short or matches no known signature.
    """
    if len(data) < 4:
        return fallback
    for signature, offset, extra, mime in _MAGIC_SIGNATURES:
        end = offset + len(signature)
        if data[offset:end] == signature:
            if extra is None:
                return mime
            extra_start = 8  # RIFF(4) + filesize(4)
            if data[extra_start : extra_start + len(extra)] == extra:
                return mime
    return fallback


def extension_for_mime(mime: str, fallback: str = "png") -> str:
    """Return a file extension (without dot) for *mime*."""
    return _MIME_TO_EXTENSION.get(mime, fallback)
