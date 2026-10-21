"""File processing utility functions.

[INPUT]

[OUTPUT]
- extract_file_id_from_url: str | None (extracted file ID)

[POS]
Pure file URL parsing utilities. No business logic dependencies.
"""

from __future__ import annotations

import re

# Regex to extract file_id from URL
# Matches /files/storage/files/{file_id}/content or /files/{file_id}/content
_FILE_ID_PATTERN = re.compile(r"/files/(?:storage/files/)?([^/]+)/content")


def extract_file_id_from_url(url: str) -> str | None:
    """Extract file_id from file content URL.

    Supports formats:
    - /files/storage/files/{file_id}/content
    - /files/{file_id}/content

    Args:
        url: File content URL

    Returns:
        Extracted file_id, or None if not found

    Example:
        >>> extract_file_id_from_url("/files/abc123/content")
        'abc123'
        >>> extract_file_id_from_url("/files/storage/files/xyz789/content")
        'xyz789'
    """
    match = _FILE_ID_PATTERN.search(url)
    return match.group(1) if match else None
