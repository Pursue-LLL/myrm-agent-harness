"""Shared image encoding utilities for video generation providers.

[INPUT]
- utils.mime_types::detect_image_mime (POS: centralized magic-bytes MIME detection)

[OUTPUT]
- detect_image_mime: Re-export for video provider convenience
- encode_image_data_url: Encode raw image bytes as a base64 data URL
- encode_image_base64: Encode raw image bytes as plain base64 string

[POS]
Shared image encoding utilities for video generation providers.
"""

from __future__ import annotations

import base64

from myrm_agent_harness.utils.mime_types import detect_image_mime

__all__ = ["detect_image_mime", "encode_image_base64", "encode_image_data_url"]


def encode_image_data_url(data: bytes) -> str:
    """Encode raw image bytes as a base64 data URL (data:{mime};base64,...)."""
    b64 = base64.b64encode(data).decode("ascii")
    mime = detect_image_mime(data)
    return f"data:{mime};base64,{b64}"


def encode_image_base64(data: bytes) -> str:
    """Encode raw image bytes as plain base64 string (no data URL prefix)."""
    return base64.b64encode(data).decode("ascii")
