"""Media utilities for image/video compression.

Provides compression tools for common media formats.

Example:
    >>> from myrm_agent_harness.utils.media import image_compressor
    >>> compressed = image_compressor.compress("input.jpg", quality=0.8)
"""

from .image_compressor import ImageCompressor, image_compressor

__all__ = [
    "ImageCompressor",
    "image_compressor",
]
