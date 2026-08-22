"""Media utilities for image/video compression.

[INPUT]
- .image_compressor::ImageCompressor, image_compressor, SEND_COMPRESS_*

[OUTPUT]
- ImageCompressor, image_compressor, SEND_COMPRESS_*

[POS]
Media compression utilities package entry point.
"""

from .image_compressor import (
    SEND_COMPRESS_MAX_DIMENSION,
    SEND_COMPRESS_QUALITY,
    SEND_COMPRESS_TRIGGER_BYTES,
    ImageCompressor,
    image_compressor,
)

__all__ = [
    "SEND_COMPRESS_MAX_DIMENSION",
    "SEND_COMPRESS_QUALITY",
    "SEND_COMPRESS_TRIGGER_BYTES",
    "ImageCompressor",
    "image_compressor",
]
