"""Media utilities for image/video compression.

[INPUT]
- .image_compressor::ImageCompressor, image_compressor, SEND_COMPRESS_*

[OUTPUT]
- ImageCompressor, image_compressor, SEND_COMPRESS_*

[POS]
Media compression utilities package entry point.
"""

from .base64_downsampler import (
    DEFAULT_DOWNSAMPLE_MAX_DIM,
    DEFAULT_DOWNSAMPLE_QUALITY,
    downsample_base64_image,
    probe_base64_image_meta,
)
from .image_compressor import (
    SEND_COMPRESS_MAX_DIMENSION,
    SEND_COMPRESS_QUALITY,
    SEND_COMPRESS_TRIGGER_BYTES,
    ImageCompressor,
    image_compressor,
)

__all__ = [
    "DEFAULT_DOWNSAMPLE_MAX_DIM",
    "DEFAULT_DOWNSAMPLE_QUALITY",
    "ImageCompressor",
    "SEND_COMPRESS_MAX_DIMENSION",
    "SEND_COMPRESS_QUALITY",
    "SEND_COMPRESS_TRIGGER_BYTES",
    "downsample_base64_image",
    "image_compressor",
    "probe_base64_image_meta",
]
